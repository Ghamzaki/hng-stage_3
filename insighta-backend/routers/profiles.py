import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from typing import Optional
import uuid6
from datetime import datetime, timezone

from database import get_pool
from models import ProfileRequest, ProfileFull, ProfileSummary
from services.external import fetch_all
from services.classifier import get_age_group, get_top_country
from services.parser import parse_query, COUNTRY_MAP
from middleware.auth import (
    get_current_user,
    require_admin,
    require_analyst_or_admin,
    check_api_version,
)

router = APIRouter(
    prefix="/api/profiles",
    dependencies=[Depends(check_api_version)],
)

VALID_SORT_FIELDS = {"age", "created_at", "gender_probability"}
VALID_ORDERS = {"asc", "desc"}
COUNTRY_NAME_MAP = {v: k.title() for k, v in COUNTRY_MAP.items()}


def _format_row(row) -> dict:
    d = dict(row)
    if isinstance(d.get("created_at"), datetime):
        d["created_at"] = d["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
    return d


def _build_links(request: Request, page: int, limit: int, total: int) -> dict:
    total_pages = (total + limit - 1) // limit
    base = str(request.url.path)

    def page_url(p):
        params = dict(request.query_params)
        params["page"] = str(p)
        params["limit"] = str(limit)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"

    return {
        "self": page_url(page),
        "next": page_url(page + 1) if page < total_pages else None,
        "prev": page_url(page - 1) if page > 1 else None,
    }


async def _query_profiles(
    conn,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    country_id: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
    sort_by: Optional[str] = "created_at",
    order: Optional[str] = "asc",
    page: int = 1,
    limit: int = 10,
):
    conditions = ["1=1"]
    params = []
    i = 1

    if gender:
        conditions.append(f"LOWER(gender) = ${i}"); params.append(gender.lower()); i += 1
    if age_group:
        conditions.append(f"LOWER(age_group) = ${i}"); params.append(age_group.lower()); i += 1
    if country_id:
        conditions.append(f"UPPER(country_id) = ${i}"); params.append(country_id.upper()); i += 1
    if min_age is not None:
        conditions.append(f"age >= ${i}"); params.append(min_age); i += 1
    if max_age is not None:
        conditions.append(f"age <= ${i}"); params.append(max_age); i += 1
    if min_gender_probability is not None:
        conditions.append(f"gender_probability >= ${i}"); params.append(min_gender_probability); i += 1
    if min_country_probability is not None:
        conditions.append(f"country_probability >= ${i}"); params.append(min_country_probability); i += 1

    where = " AND ".join(conditions)
    sort_col = sort_by if sort_by in VALID_SORT_FIELDS else "created_at"
    sort_dir = order.upper() if order in VALID_ORDERS else "ASC"

    total = await conn.fetchval(f"SELECT COUNT(*) FROM profiles WHERE {where}", *params)
    offset = (page - 1) * limit
    rows = await conn.fetch(
        f"""
        SELECT id, name, gender, gender_probability, age, age_group,
               country_id, country_name, country_probability, created_at
        FROM profiles WHERE {where}
        ORDER BY {sort_col} {sort_dir}
        LIMIT ${i} OFFSET ${i+1}
        """,
        *params, limit, offset,
    )
    return total, [ProfileSummary(**_format_row(r)) for r in rows]


# ── POST /api/profiles — admin only ─────────────────────────────────────────

@router.post("", status_code=201)
async def create_profile(
    body: ProfileRequest,
    _user: dict = Depends(require_admin),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing or empty name")

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM profiles WHERE name = $1", name.lower()
        )
        if existing:
            return {
                "status": "success",
                "message": "Profile already exists",
                "data": ProfileFull(**_format_row(existing)),
            }

    gender_data, age_data, nation_data = await fetch_all(name)
    age_group = get_age_group(age_data["age"])
    country_id, country_probability = get_top_country(nation_data["country"])
    country_name = COUNTRY_NAME_MAP.get(country_id, country_id)

    profile = {
        "id": str(uuid6.uuid7()),
        "name": name.lower(),
        "gender": gender_data["gender"],
        "gender_probability": gender_data["probability"],
        "age": age_data["age"],
        "age_group": age_group,
        "country_id": country_id,
        "country_name": country_name,
        "country_probability": country_probability,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO profiles
                (id, name, gender, gender_probability, age, age_group,
                 country_id, country_name, country_probability, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
            profile["id"], profile["name"], profile["gender"],
            profile["gender_probability"], profile["age"], profile["age_group"],
            profile["country_id"], profile["country_name"],
            profile["country_probability"],
            datetime.now(timezone.utc).replace(tzinfo=None),
        )

    return {"status": "success", "data": ProfileFull(**profile)}


# ── GET /api/profiles/export — admin or analyst ──────────────────────────────

@router.get("/export")
async def export_profiles(
    request: Request,
    format: str = Query("csv"),
    gender: Optional[str] = Query(None),
    age_group: Optional[str] = Query(None),
    country_id: Optional[str] = Query(None),
    min_age: Optional[int] = Query(None),
    max_age: Optional[int] = Query(None),
    sort_by: Optional[str] = Query("created_at"),
    order: Optional[str] = Query("asc"),
    _user: dict = Depends(require_analyst_or_admin),
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only format=csv is supported")

    # Build filter conditions
    conditions = ["1=1"]
    params = []
    i = 1
    if gender:
        conditions.append(f"LOWER(gender) = ${i}"); params.append(gender.lower()); i += 1
    if age_group:
        conditions.append(f"LOWER(age_group) = ${i}"); params.append(age_group.lower()); i += 1
    if country_id:
        conditions.append(f"UPPER(country_id) = ${i}"); params.append(country_id.upper()); i += 1
    if min_age is not None:
        conditions.append(f"age >= ${i}"); params.append(min_age); i += 1
    if max_age is not None:
        conditions.append(f"age <= ${i}"); params.append(max_age); i += 1

    where = " AND ".join(conditions)
    sort_col = sort_by if sort_by in VALID_SORT_FIELDS else "created_at"
    sort_dir = order.upper() if order in VALID_ORDERS else "ASC"

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, name, gender, gender_probability, age, age_group,
                   country_id, country_name, country_probability, created_at
            FROM profiles WHERE {where}
            ORDER BY {sort_col} {sort_dir}
            """,
            *params,
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "gender", "gender_probability", "age", "age_group",
        "country_id", "country_name", "country_probability", "created_at",
    ])
    for row in rows:
        d = _format_row(row)
        writer.writerow([
            d["id"], d["name"], d["gender"], d["gender_probability"],
            d["age"], d["age_group"], d["country_id"], d["country_name"],
            d["country_probability"], d["created_at"],
        ])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"profiles_{timestamp}.csv"
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── GET /api/profiles/search — analyst or admin ──────────────────────────────

@router.get("/search")
async def search_profiles(
    request: Request,
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(require_analyst_or_admin),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Missing or empty query")

    filters = parse_query(q.strip())
    if filters is None:
        raise HTTPException(status_code=400, detail="Unable to interpret query")

    pool = await get_pool()
    async with pool.acquire() as conn:
        total, data = await _query_profiles(conn, page=page, limit=limit, **filters)

    total_pages = (total + limit - 1) // limit
    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": _build_links(request, page, limit, total),
        "data": data,
    }


# ── GET /api/profiles — analyst or admin ─────────────────────────────────────

@router.get("")
async def get_all_profiles(
    request: Request,
    gender: Optional[str] = Query(None),
    age_group: Optional[str] = Query(None),
    country_id: Optional[str] = Query(None),
    min_age: Optional[int] = Query(None),
    max_age: Optional[int] = Query(None),
    min_gender_probability: Optional[float] = Query(None),
    min_country_probability: Optional[float] = Query(None),
    sort_by: Optional[str] = Query("created_at"),
    order: Optional[str] = Query("asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(require_analyst_or_admin),
):
    if sort_by and sort_by not in VALID_SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Invalid query parameters")
    if order and order not in VALID_ORDERS:
        raise HTTPException(status_code=400, detail="Invalid query parameters")

    pool = await get_pool()
    async with pool.acquire() as conn:
        total, data = await _query_profiles(
            conn,
            gender=gender, age_group=age_group, country_id=country_id,
            min_age=min_age, max_age=max_age,
            min_gender_probability=min_gender_probability,
            min_country_probability=min_country_probability,
            sort_by=sort_by, order=order, page=page, limit=limit,
        )

    total_pages = (total + limit - 1) // limit
    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": _build_links(request, page, limit, total),
        "data": data,
    }


# ── GET /api/profiles/{id} — analyst or admin ────────────────────────────────

@router.get("/{profile_id}")
async def get_profile(
    profile_id: str,
    _user: dict = Depends(require_analyst_or_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM profiles WHERE id = $1", profile_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "success", "data": ProfileFull(**_format_row(row))}


# ── DELETE /api/profiles/{id} — admin only ───────────────────────────────────

@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    _user: dict = Depends(require_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM profiles WHERE id = $1", profile_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Profile not found")
    return Response(status_code=204)

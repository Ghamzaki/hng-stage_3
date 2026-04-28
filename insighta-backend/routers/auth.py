import os
import secrets
import uuid6
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse

from database import get_pool
from models import RefreshRequest
from services.auth import (
    create_access_token,
    create_refresh_token,
    REFRESH_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


def _format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _upsert_user_and_issue_tokens(github_user: dict) -> tuple[str, str, dict]:
    """Create or update user from GitHub data, return (access_token, refresh_token, user)."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM users WHERE github_id = $1",
            str(github_user["id"]),
        )

        if existing:
            user = await conn.fetchrow("""
                UPDATE users
                SET username = $1, email = $2, avatar_url = $3,
                    last_login_at = $4
                WHERE github_id = $5
                RETURNING *
            """,
                github_user.get("login"),
                github_user.get("email"),
                github_user.get("avatar_url"),
                now_naive,
                str(github_user["id"]),
            )
        else:
            user_id = str(uuid6.uuid7())
            user = await conn.fetchrow("""
                INSERT INTO users
                    (id, github_id, username, email, avatar_url,
                     role, is_active, last_login_at, created_at)
                VALUES ($1,$2,$3,$4,$5,'analyst',TRUE,$6,$7)
                RETURNING *
            """,
                user_id,
                str(github_user["id"]),
                github_user.get("login"),
                github_user.get("email"),
                github_user.get("avatar_url"),
                now_naive,
                now_naive,
            )

        user = dict(user)
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account is inactive")

        # Issue refresh token
        refresh_token = create_refresh_token()
        token_id = str(uuid6.uuid7())
        expires_at = (now + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)).replace(tzinfo=None)

        await conn.execute("""
            INSERT INTO refresh_tokens (id, user_id, token, expires_at, used, created_at)
            VALUES ($1,$2,$3,$4,FALSE,$5)
        """,
            token_id, user["id"], refresh_token, expires_at, now_naive,
        )

    access_token = create_access_token(user["id"], user["username"], user["role"])
    return access_token, refresh_token, user


# ── GET /auth/github ─────────────────────────────────────────────────────────

@router.get("/github")
async def github_login(
    state: str = Query(None),
    code_challenge: str = Query(None),
    code_challenge_method: str = Query(None),
):
    """
    Redirect to GitHub OAuth.
    Accepts optional PKCE params from CLI (state, code_challenge).
    For browser flow these are omitted and we generate state server-side.
    """
    if not state:
        state = secrets.token_urlsafe(32)

    callback_url = f"{BACKEND_URL}/auth/github/callback"

    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": callback_url,
        "scope": "read:user user:email",
        "state": state,
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")


# ── GET /auth/github/callback ────────────────────────────────────────────────

@router.get("/github/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    code_verifier: str = Query(None),
    redirect_to: str = Query(None),
    response: Response = None,
):
    """
    Handle GitHub OAuth callback for both CLI and browser.
    - CLI sends code_verifier (PKCE); we pass it along.
    - Browser flow omits code_verifier.
    - redirect_to controls where browser is sent after login.
    """
    # Exchange code for GitHub access token
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{BACKEND_URL}/auth/github/callback",
            },
        )

    token_data = token_resp.json()
    gh_token = token_data.get("access_token")
    if not gh_token:
        raise HTTPException(status_code=502, detail="GitHub token exchange failed")

    # Fetch GitHub user info
    async with httpx.AsyncClient(timeout=10.0) as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {gh_token}"},
        )
        github_user = user_resp.json()

        # Fetch email if not public
        if not github_user.get("email"):
            email_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {gh_token}"},
            )
            emails = email_resp.json()
            primary = next((e["email"] for e in emails if e.get("primary")), None)
            github_user["email"] = primary

    access_token, refresh_token, user = await _upsert_user_and_issue_tokens(github_user)

    # CLI flow: return JSON
    if code_verifier is not None or redirect_to is None:
        return JSONResponse({
            "status": "success",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
            },
        })

    # Browser flow: redirect back to portal with tokens as one-time query params
    # The portal's /auth/callback will read these and set its own HTTP-only cookies
    from urllib.parse import urlencode
    dest = redirect_to or f"{FRONTEND_URL}/auth/callback"
    params = urlencode({"access_token": access_token, "refresh_token": refresh_token})
    resp = RedirectResponse(url=f"{dest}?{params}", status_code=302)
    return resp


# ── POST /auth/refresh ───────────────────────────────────────────────────────

@router.post("/refresh")
async def refresh_tokens(body: RefreshRequest, request: Request):
    """Rotate token pair. Old refresh token is invalidated immediately."""
    # Support cookie-based refresh too (web portal)
    token = (body.refresh_token or "").strip() or request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    pool = await get_pool()
    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    async with pool.acquire() as conn:
        rt = await conn.fetchrow(
            "SELECT * FROM refresh_tokens WHERE token = $1", token
        )

        if not rt:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if rt["used"]:
            raise HTTPException(status_code=401, detail="Refresh token already used")
        if rt["expires_at"] < now_naive:
            raise HTTPException(status_code=401, detail="Refresh token expired")

        # Invalidate old token
        await conn.execute(
            "UPDATE refresh_tokens SET used = TRUE WHERE id = $1", rt["id"]
        )

        user = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", rt["user_id"]
        )
        if not user or not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account inactive")

        # Issue new pair
        new_refresh = create_refresh_token()
        token_id = str(uuid6.uuid7())
        expires_at = (now + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)).replace(tzinfo=None)

        await conn.execute("""
            INSERT INTO refresh_tokens (id, user_id, token, expires_at, used, created_at)
            VALUES ($1,$2,$3,$4,FALSE,$5)
        """,
            token_id, user["id"], new_refresh, expires_at, now_naive,
        )

    new_access = create_access_token(user["id"], user["username"], user["role"])

    return {
        "status": "success",
        "access_token": new_access,
        "refresh_token": new_refresh,
    }


# ── POST /auth/logout ────────────────────────────────────────────────────────

# ── GET /auth/me ─────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(request: Request):
    """Return current user info from token (used by web portal)."""
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from middleware.auth import get_current_user
    from fastapi import Depends
    # Read token from header or cookie
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from services.auth import decode_access_token
    payload = decode_access_token(token)
    user_id = payload["sub"]

    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account inactive")

    u = dict(user)
    return {
        "status": "success",
        "data": {
            "id": u["id"],
            "username": u["username"],
            "email": u["email"],
            "avatar_url": u["avatar_url"],
            "role": u["role"],
            "is_active": u["is_active"],
        }
    }


@router.post("/logout")
async def logout(request: Request):
    """Invalidate refresh token server-side."""
    token = request.cookies.get("refresh_token")
    # Also accept JSON body for CLI
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("refresh_token"):
            token = body["refresh_token"]
    except Exception:
        pass

    if token:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE refresh_tokens SET used = TRUE WHERE token = $1", token
            )

    resp = JSONResponse({"status": "success", "message": "Logged out"})
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp

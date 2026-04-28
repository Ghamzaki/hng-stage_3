import os
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_pool
from services.auth import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Extract and validate JWT; return user dict from DB."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials)
    user_id = payload["sub"]

    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is inactive")

    return dict(user)


async def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(
            status_code=403, detail="Admin access required"
        )
    return user


async def require_analyst_or_admin(user: dict = Depends(get_current_user)):
    """Both roles can read."""
    if user["role"] not in ("admin", "analyst"):
        raise HTTPException(status_code=403, detail="Access denied")
    return user


async def check_api_version(x_api_version: str = Header(None, alias="X-API-Version")):
    """Enforce X-API-Version: 1 header on all /api/* routes."""
    if x_api_version != "1":
        raise HTTPException(
            status_code=400,
            detail="API version header required",
        )


# ── Cookie-based auth for web portal ────────────────────────────────────────

async def get_current_user_cookie(request: Request):
    """Read access token from HTTP-only cookie (web portal)."""
    token = request.cookies.get("access_token")
    if not token:
        return None  # caller decides how to handle (redirect vs 401)

    try:
        payload = decode_access_token(token)
    except HTTPException:
        return None

    user_id = payload["sub"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )

    if not user or not user["is_active"]:
        return None

    return dict(user)

from fastapi import APIRouter, HTTPException, Request
from database import get_pool

router = APIRouter(prefix="/api/users", tags=["users"])

@router.get("/me")
async def get_user_me(request: Request):
    """Return current user info from token."""
    from services.auth import decode_access_token
    
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
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

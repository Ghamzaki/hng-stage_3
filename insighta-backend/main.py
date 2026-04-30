import time
import logging
from collections import defaultdict
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import init_db, seed_db
from routers.profiles import router as profiles_router
from routers.auth import router as auth_router
from routers.users import router as users_router

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("insighta")

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Simple in-process sliding-window counters: {key: [(timestamp, count)]}
_rate_buckets: dict[str, list] = defaultdict(list)

AUTH_LIMIT = 10       # per minute
DEFAULT_LIMIT = 60    # per minute


def _check_rate_limit(key: str, limit: int) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    window = 60.0
    bucket = _rate_buckets[key]
    # Drop entries older than 1 min
    _rate_buckets[key] = [t for t in bucket if now - t < window]
    if len(_rate_buckets[key]) >= limit:
        return False
    _rate_buckets[key].append(now)
    return True


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Insighta Labs+")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.middleware("http")
async def rate_limit_and_log(request: Request, call_next):
    start = time.time()
    path = request.url.path
    method = request.method

    # Determine rate limit key and ceiling
    client_ip = request.client.host if request.client else "unknown"
    is_auth = path.startswith("/auth")

    if is_auth:
        key = f"auth:{client_ip}"
        limit = AUTH_LIMIT
    else:
        # Per-user (by IP as fallback; JWT user would need token parse here)
        key = f"user:{client_ip}"
        limit = DEFAULT_LIMIT

    if not _check_rate_limit(key, limit):
        logger.warning("Rate limited | %s %s | %s", method, path, client_ip)
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "Too many requests"},
        )

    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)

    logger.info(
        "%s %s | %s | %.2fms",
        method, path, response.status_code, duration_ms,
    )
    return response


app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(users_router)


@app.on_event("startup")
async def startup():
    await init_db()
    await seed_db()


# ── Global exception handlers ─────────────────────────────────────────────────

@app.exception_handler(400)
async def bad_request_handler(request: Request, exc):
    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return JSONResponse(
        status_code=401,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return JSONResponse(
        status_code=403,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.exception_handler(422)
async def unprocessable_handler(request: Request, exc):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid parameter type"},
    )


@app.exception_handler(429)
async def too_many_requests_handler(request: Request, exc):
    return JSONResponse(
        status_code=429,
        content={"status": "error", "message": "Too many requests"},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )


@app.exception_handler(502)
async def bad_gateway_handler(request: Request, exc):
    return JSONResponse(
        status_code=502,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.get("/health")
async def health():
    return {"status": "success"}

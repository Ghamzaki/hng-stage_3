# Insighta Labs+ — Backend

Secure REST API powering the Insighta Labs+ platform. Built with FastAPI, asyncpg, and PostgreSQL (Neon).

## System Architecture

```
insighta-backend/
├── main.py              # App entrypoint, rate limiting, logging, exception handlers
├── database.py          # Connection pool, table init, seed
├── models.py            # Pydantic models
├── routers/
│   ├── auth.py          # GitHub OAuth, token refresh, logout, /me
│   └── profiles.py      # Profile CRUD, search, export (all authenticated)
├── services/
│   ├── auth.py          # JWT creation/decoding
│   ├── classifier.py    # Age group logic
│   ├── external.py      # Genderize / Agify / Nationalize API calls
│   └── parser.py        # Natural language query parser
└── middleware/
    └── auth.py          # get_current_user, require_admin, require_analyst_or_admin, check_api_version
```

## Authentication Flow

### CLI (PKCE)
1. CLI generates `state`, `code_verifier`, `code_challenge` (SHA-256 of verifier, base64url encoded)
2. CLI starts a local HTTP callback server on a random port
3. CLI opens `GET /auth/github?state=&code_challenge=` in browser
4. User authenticates on GitHub, which redirects to `GET /auth/github/callback?code=&state=`
5. Backend exchanges code with GitHub for an access token
6. Backend fetches GitHub user info, upserts user in DB
7. Backend issues access + refresh tokens, returns JSON
8. CLI stores tokens at `~/.insighta/credentials.json`

### Browser (Web Portal)
1. User clicks "Continue with GitHub" → hits `GET /auth/github` (no PKCE params)
2. Same GitHub OAuth flow
3. Backend sets HTTP-only cookies (`access_token`, `refresh_token`) and redirects to portal

## Token Handling

| Token | Expiry | Storage (CLI) | Storage (Web) |
|---|---|---|---|
| Access token | 3 minutes | `~/.insighta/credentials.json` | HTTP-only cookie |
| Refresh token | 5 minutes | `~/.insighta/credentials.json` | HTTP-only cookie |

- Refresh tokens are **single-use** — consuming a token immediately invalidates it and issues a new pair
- On 401, clients auto-refresh before prompting re-login

## Role Enforcement

All `/api/*` endpoints require authentication via `get_current_user` dependency.

| Role | Permissions |
|---|---|
| `admin` | Full access: create, read, search, export, delete |
| `analyst` | Read-only: list, get, search, export |

Role is enforced via FastAPI `Depends`:
- `require_admin` — injected on POST/DELETE profile endpoints
- `require_analyst_or_admin` — injected on GET profile endpoints

`is_active=False` → 403 on every request regardless of role.

## API Versioning

All `/api/*` requests must include:
```
X-API-Version: 1
```
Missing or wrong value → `400 Bad Request`.

## Rate Limiting

| Scope | Limit |
|---|---|
| `/auth/*` | 10 req/min per IP |
| All other endpoints | 60 req/min per IP |

Exceeded → `429 Too Many Requests`.

## Natural Language Parsing

`services/parser.py` maps plain English queries to filter parameters:
- **Gender**: "males", "men", "women", "females" → `gender`
- **Age groups**: "children", "teenagers", "adults", "seniors" → `age_group`
- **Age ranges**: "young", "between X and Y", "over X", "under X" → `min_age` / `max_age`
- **Countries**: "from Nigeria", "in Kenya", bare ISO codes like "NG" → `country_id`

## Setup

```bash
# Clone and install
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in DATABASE_URL, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, JWT_SECRET_KEY

# Run locally
uvicorn main:app --reload

# Or deploy to Vercel
vercel --prod
```

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (Neon) |
| `GITHUB_CLIENT_ID` | GitHub OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App secret |
| `JWT_SECRET_KEY` | Secret for signing JWTs |
| `BACKEND_URL` | Public URL of this backend |
| `FRONTEND_URL` | Public URL of the web portal |

## GitHub OAuth App Setup

1. Go to GitHub → Settings → Developer Settings → OAuth Apps → New OAuth App
2. Set **Authorization callback URL** to `https://your-backend.vercel.app/auth/github/callback`
3. Copy Client ID and Secret into `.env`
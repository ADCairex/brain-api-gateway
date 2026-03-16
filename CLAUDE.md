# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

**api-gateway** is the single entry point for all external API traffic in the brain-app platform. It validates JWT tokens (from httpOnly cookies) and proxies requests to the correct downstream service. It runs on port **8000** and is the only service exposed publicly — downstream services are not reachable from outside the Docker network.

No database. No business logic. No token issuance.

## Commands

```bash
uv sync                                                               # Install dependencies
uv run python -m uvicorn src.api.app:app --reload --port 8000        # Start dev server
uv run python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000  # Production start

make run                  # Alias for dev server
make lint                 # Lint with ruff
make test                 # Run tests
```

Environment: copy `.env.example` to `.env` and fill in `SECRET_KEY` (must match brain-auth-service).

## Architecture

FastAPI + httpx (async proxying). No SQLAlchemy, no Alembic, no database.

```
src/api/
├── app.py       # FastAPI instance, CORS, single catch-all route
├── config.py    # SERVICE_MAP, PUBLIC_PATHS, pydantic-settings
├── auth.py      # JWT validation from access_token cookie
└── proxy.py     # httpx async proxy, injects X-User-Id header
```

## Request lifecycle

1. Request arrives at `/{path:path}`
2. `_resolve_target(path)` looks up the upstream URL in `SERVICE_MAP`
3. If path is in `PUBLIC_PATHS` → skip auth, proxy directly
4. Otherwise → `validate_token()` reads `access_token` cookie, decodes JWT with `SECRET_KEY`
   - On failure → 401, request is NOT forwarded
   - On success → extract `sub` (user ID), set as `X-User-Id` header
5. `proxy_request()` forwards the full request (method, headers, body, query params) to upstream

## Routing

```python
PUBLIC_PATHS = [
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
]

SERVICE_MAP = {
    "/auth":    "http://brain-auth-service:8001",
    "/finance": "http://brain-finance-service:8002",
}
```

SERVICE_MAP keys use internal Docker service names — never `localhost`.

## Key patterns

- **JWT validation**: PyJWT, algorithm HS256, `SECRET_KEY` from environment only.
- **Token source**: `access_token` httpOnly cookie — never Authorization header.
- **User identity**: extracted from JWT `sub` claim, forwarded as `X-User-Id` header to upstream services.
- **Proxy**: httpx `AsyncClient`, strips `host` and hop-by-hop headers before forwarding.
- **CORS**: `allow_credentials=True` required for cookie-based auth to work with the frontend.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | JWT signing secret — must match brain-auth-service |
| `SERVICE_AUTH_URL` | `http://brain-auth-service:8001` | Auth service URL |
| `SERVICE_FINANCE_URL` | `http://brain-finance-service:8002` | Finance service URL |
| `PORT` | 8000 | Listening port |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |
| `ENVIRONMENT` | development | Runtime environment |

## What NOT to do

- Do not add business logic — this is a pure proxy/auth-validator.
- Do not issue or refresh tokens — that is brain-auth-service's job.
- Do not connect to any database.
- Do not hardcode `SECRET_KEY` — environment variable only.
- Do not expose downstream services directly — all traffic must go through this gateway.
- Do not add routes to SERVICE_MAP without also considering whether they need auth or belong in PUBLIC_PATHS.

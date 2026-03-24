from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .auth import validate_token
from .config import PUBLIC_STRIPPED_PATHS, SERVICE_MAP
from .limiter import limiter
from .proxy import proxy_request

app = FastAPI(title="API Gateway", version="0.1.0")

# Attach the limiter to the app state (required by slowapi)
app.state.limiter = limiter

# Rate limit exceeded → 429 Too Many Requests
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# SlowAPIMiddleware must be added BEFORE CORSMiddleware so that rate limiting
# happens on every request regardless of origin.
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cairex-brain.com", "https://www.cairex-brain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_target(path: str) -> tuple[str, str] | None:
    """Return (upstream_url, stripped_path) for the given path, or None if no match."""
    for prefix, service_url in SERVICE_MAP.items():
        if path.startswith(prefix):
            remainder = path[len(prefix) :]
            return service_url + remainder, remainder
    return None


# ---------------------------------------------------------------------------
# Auth endpoints with strict per-route rate limits.
# These specific routes are registered BEFORE the catch-all so FastAPI matches
# them first.  The limits apply per real client IP (see limiter.py).
# ---------------------------------------------------------------------------


@app.post("/auth/login")
@limiter.limit("5/minute")
async def auth_login(request: Request) -> Response:
    """Proxy /auth/login with a strict 5 req/min limit per IP."""
    target_url, _ = _resolve_target("/auth/login")  # type: ignore[misc]
    return await proxy_request(request, target_url, user_id=None)


@app.post("/auth/register")
@limiter.limit("3/minute")
async def auth_register(request: Request) -> Response:
    """Proxy /auth/register with a strict 3 req/min limit per IP."""
    target_url, _ = _resolve_target("/auth/register")  # type: ignore[misc]
    return await proxy_request(request, target_url, user_id=None)


@app.post("/auth/refresh")
@limiter.limit("10/minute")
async def auth_refresh(request: Request) -> Response:
    """Proxy /auth/refresh with a strict 10 req/min limit per IP."""
    target_url, _ = _resolve_target("/auth/refresh")  # type: ignore[misc]
    return await proxy_request(request, target_url, user_id=None)


# ---------------------------------------------------------------------------
# Generic catch-all proxy — global limit (100/minute) via default_limits.
# ---------------------------------------------------------------------------


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@limiter.limit("100/minute")
async def gateway(path: str, request: Request) -> Response:
    full_path = f"/{path}"

    result = _resolve_target(full_path)
    if result is None:
        return Response(
            content='{"detail":"Not found"}',
            status_code=404,
            media_type="application/json",
        )

    target_url, stripped_path = result

    user_id: str | None = None
    if stripped_path not in PUBLIC_STRIPPED_PATHS:
        payload = validate_token(request)
        user_id = payload.get("sub")

    return await proxy_request(request, target_url, user_id)

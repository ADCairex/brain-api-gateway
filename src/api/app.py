from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .auth import validate_token
from .config import PUBLIC_PATHS, SERVICE_MAP, settings
from .proxy import proxy_request

app = FastAPI(title="API Gateway", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_target(path: str) -> str | None:
    """Return the upstream base URL for the given path, or None if no match."""
    for prefix, service_url in SERVICE_MAP.items():
        if path.startswith(prefix):
            return service_url + path
    return None


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway(path: str, request: Request) -> Response:
    full_path = f"/{path}"

    target_url = _resolve_target(full_path)
    if target_url is None:
        return Response(
            content='{"detail":"Not found"}',
            status_code=404,
            media_type="application/json",
        )

    user_id: str | None = None
    if full_path not in PUBLIC_PATHS:
        payload = validate_token(request)
        user_id = payload.get("sub")

    return await proxy_request(request, target_url, user_id)

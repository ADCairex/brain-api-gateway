import httpx
from fastapi import Request, Response

from .config import settings


def _upstream_timeout(target_url: str) -> float:
    if target_url.startswith(settings.service_ocr_url):
        return settings.service_ocr_timeout_seconds
    return settings.proxy_timeout_seconds


async def proxy_request(
    request: Request,
    target_url: str,
    user_id: str | None = None,
) -> Response:
    """Forward the incoming request to target_url, optionally injecting X-User-Id."""
    headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "x-user-id"}}
    if user_id is not None:
        headers["X-User-Id"] = user_id

    body = await request.body()
    timeout = _upstream_timeout(target_url)

    async with httpx.AsyncClient(timeout=timeout) as client:
        upstream = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
            follow_redirects=True,
        )

    # Forward upstream response back to the caller, stripping hop-by-hop headers
    excluded = {"transfer-encoding", "connection"}
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded}

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )

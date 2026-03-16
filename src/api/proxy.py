import httpx
from fastapi import Request, Response


async def proxy_request(
    request: Request,
    target_url: str,
    user_id: str | None = None,
) -> Response:
    """Forward the incoming request to target_url, optionally injecting X-User-Id."""
    headers = dict(request.headers)
    headers.pop("host", None)
    if user_id is not None:
        headers["X-User-Id"] = user_id

    body = await request.body()

    async with httpx.AsyncClient() as client:
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
    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in excluded
    }

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )

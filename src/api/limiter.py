from fastapi import Request
from slowapi import Limiter


def _get_real_ip(request: Request) -> str:
    """
    Extract the real client IP address.

    Behind Traefik (or any reverse proxy), the actual client IP is forwarded
    via the X-Forwarded-For header.  We take the first (leftmost) entry which
    is the original client, not an intermediate proxy.

    Falls back to the direct connection IP when the header is absent (e.g.
    during local development or direct access).
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_ip, default_limits=["100/minute"])

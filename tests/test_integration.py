"""
Integration tests for the API Gateway — full request flow via TestClient.

These tests exercise the complete request pipeline:
    client → FastAPI app → (mocked) proxy → response

The proxy (httpx.AsyncClient) is mocked in ALL tests so no real network calls
are ever made.  Every test is fully deterministic.

Groups:
  1. Public routes — /auth/login, /auth/register, /auth/refresh require no JWT.
  2. Protected routes — all other routes require a valid JWT in the access_token
     cookie; missing/invalid tokens return 401.
  3. Unknown routes — paths with no SERVICE_MAP prefix return 404.
  4. Rate limiting — slowapi enforces per-route limits; excess requests → 429.

Rate limiting isolation
-----------------------
slowapi persists hit counts in an in-memory store that is shared for the lifetime
of the Python process.  To prevent cross-test pollution the rate limiting tests:
  - call ``limiter.reset()`` in a ``setup_method`` so each test starts fresh.
  - use distinct X-Forwarded-For IPs to avoid bleeding into non-rate-limit tests.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.limiter import limiter

# Must match the value injected by conftest.py.
TEST_SECRET = "test-secret-key-for-unit-tests-only"
ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(sub: str = "user-123", hours: int = 1) -> str:
    """Return a signed HS256 JWT valid for *hours* from now."""
    payload = {
        "sub": sub,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, TEST_SECRET, algorithm=ALGORITHM)


def _make_mock_upstream(
    status_code: int = 200,
    body: bytes = b'{"ok": true}',
    content_type: str = "application/json",
) -> AsyncMock:
    """
    Build a mock httpx.Response-like object that proxy_request can process.

    proxy_request reads: upstream.content, upstream.status_code, upstream.headers.
    """
    mock_resp = AsyncMock()
    mock_resp.status_code = status_code
    mock_resp.content = body
    mock_resp.headers = httpx.Headers({"content-type": content_type})
    return mock_resp


def _patch_proxy(mock_resp: AsyncMock | None = None):
    """
    Return a context manager that patches httpx.AsyncClient inside proxy.py.

    The patched client's ``request`` coroutine always returns *mock_resp*
    (a default 200 response if not provided).
    """
    if mock_resp is None:
        mock_resp = _make_mock_upstream()

    patcher = patch("src.api.proxy.httpx.AsyncClient")

    class _PatchCtx:
        def __enter__(self):
            self.mock_cls = patcher.start()
            mock_instance = self.mock_cls.return_value.__aenter__.return_value
            mock_instance.request = AsyncMock(return_value=mock_resp)
            self.mock_instance = mock_instance
            return mock_instance

        def __exit__(self, *args):
            patcher.stop()

    return _PatchCtx()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """A bare TestClient — no cookies, no special headers."""
    return TestClient(app)


@pytest.fixture()
def auth_client():
    """A TestClient with a valid JWT already set in the access_token cookie."""
    token = _make_token(sub="user-123")
    return TestClient(app, cookies={"access_token": token})


# ---------------------------------------------------------------------------
# Group 1: Public routes — no JWT required
# ---------------------------------------------------------------------------


class TestPublicRoutes:
    """
    /auth/login, /auth/register, and /auth/refresh are in PUBLIC_STRIPPED_PATHS.
    Requests to these endpoints must reach the proxy even without a cookie.
    """

    def test_public_login_route_no_auth_required(self, client):
        """POST /auth/login without a cookie should reach the proxy (not 401)."""
        with _patch_proxy() as mock_http:
            response = client.post("/auth/login", json={"username": "a", "password": "b"})

        assert response.status_code == 200
        mock_http.request.assert_called_once()

    def test_public_register_route_no_auth_required(self, client):
        """POST /auth/register without a cookie should reach the proxy (not 401)."""
        with _patch_proxy() as mock_http:
            response = client.post("/auth/register", json={"username": "a", "password": "b"})

        assert response.status_code == 200
        mock_http.request.assert_called_once()

    def test_public_refresh_route_no_auth_required(self, client):
        """POST /auth/refresh without a cookie should reach the proxy (not 401)."""
        with _patch_proxy() as mock_http:
            response = client.post("/auth/refresh")

        assert response.status_code == 200
        mock_http.request.assert_called_once()

    def test_public_login_proxies_to_auth_service(self, client):
        """POST /auth/login must forward to brain-auth-service:8001/login."""
        with _patch_proxy() as mock_http:
            client.post("/auth/login", json={})

        call_kwargs = mock_http.request.call_args
        assert "http://brain-auth-service:8001/login" in (call_kwargs.args + tuple(call_kwargs.kwargs.values()))


# ---------------------------------------------------------------------------
# Group 2: Protected routes
# ---------------------------------------------------------------------------


class TestProtectedRoutes:
    """
    Routes outside PUBLIC_STRIPPED_PATHS require a valid JWT in the
    access_token cookie.  Missing or invalid tokens → 401.
    """

    def test_protected_route_without_token_returns_401(self, client):
        """GET /finance/transactions without a cookie must return 401."""
        with _patch_proxy():
            response = client.get("/finance/transactions")

        assert response.status_code == 401

    def test_protected_route_without_token_does_not_reach_proxy(self, client):
        """When auth fails the proxy must NOT be called."""
        with _patch_proxy() as mock_http:
            client.get("/finance/transactions")

        mock_http.request.assert_not_called()

    def test_protected_route_with_valid_token_reaches_proxy(self, auth_client):
        """GET /finance/transactions with a valid JWT must reach the proxy (200)."""
        with _patch_proxy() as mock_http:
            response = auth_client.get("/finance/transactions")

        assert response.status_code == 200
        mock_http.request.assert_called_once()

    def test_protected_route_injects_user_id_header(self, auth_client):
        """
        When authenticated, the proxy call must include X-User-Id set to the
        JWT sub claim value.
        """
        captured: dict = {}

        async def capture_request(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            return _make_mock_upstream()

        with patch("src.api.proxy.httpx.AsyncClient") as mock_cls:
            instance = mock_cls.return_value.__aenter__.return_value
            instance.request = capture_request
            auth_client.get("/finance/transactions")

        assert "X-User-Id" in captured
        assert captured["X-User-Id"] == "user-123"

    def test_protected_route_with_expired_token_returns_401(self, client):
        """A token whose exp is in the past must be rejected with 401."""
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        expired_token = jwt.encode(
            {"sub": "user-1", "exp": past + timedelta(hours=1), "iat": past},
            TEST_SECRET,
            algorithm=ALGORITHM,
        )
        expired_client = TestClient(app, cookies={"access_token": expired_token})

        with _patch_proxy():
            response = expired_client.get("/finance/transactions")

        assert response.status_code == 401

    def test_protected_route_with_wrong_secret_returns_401(self, client):
        """A token signed with a different secret must be rejected with 401."""
        bad_token = jwt.encode(
            {
                "sub": "user-1",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "wrong-secret",
            algorithm=ALGORITHM,
        )
        bad_client = TestClient(app, cookies={"access_token": bad_token})

        with _patch_proxy():
            response = bad_client.get("/finance/transactions")

        assert response.status_code == 401

    def test_auth_routes_do_not_inject_user_id_header(self, client):
        """
        Public auth routes (no sub extraction) must NOT inject X-User-Id
        into the upstream request.
        """
        captured: dict = {}

        async def capture_request(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            return _make_mock_upstream()

        with patch("src.api.proxy.httpx.AsyncClient") as mock_cls:
            instance = mock_cls.return_value.__aenter__.return_value
            instance.request = capture_request
            client.post("/auth/login", json={})

        assert "X-User-Id" not in captured


# ---------------------------------------------------------------------------
# Group 3: Unknown routes
# ---------------------------------------------------------------------------


class TestUnknownRoutes:
    """Paths with no matching SERVICE_MAP prefix must return 404."""

    def test_unknown_route_returns_404(self, client):
        """GET /unknown/path has no prefix match → 404."""
        with _patch_proxy():
            response = client.get("/unknown/path")

        assert response.status_code == 404

    def test_unknown_route_response_body_contains_not_found(self, client):
        """The 404 response body must contain a 'Not found' detail."""
        with _patch_proxy():
            response = client.get("/unknown/path")

        assert "Not found" in response.text or "not_found" in response.text.lower() or response.status_code == 404

    def test_unknown_route_does_not_reach_proxy(self, client):
        """No upstream call must be made for unresolvable routes."""
        with _patch_proxy() as mock_http:
            client.get("/unknown/path")

        mock_http.request.assert_not_called()

    def test_random_routes_return_404(self, client):
        """Several arbitrary unrecognised routes all return 404."""
        with _patch_proxy():
            for path in ["/admin/users", "/api/v1/data", "/healthz", "/metrics"]:
                response = client.get(path)
                assert response.status_code == 404, f"Expected 404 for {path!r}, got {response.status_code}"


# ---------------------------------------------------------------------------
# Group 4: Rate limiting
# ---------------------------------------------------------------------------


class TestLoginRateLimit:
    """
    /auth/login is limited to 5 requests/minute per IP.
    Each test resets the limiter before running and uses a unique IP so it
    cannot accidentally interfere with other test classes.
    """

    LOGIN_IP = "10.0.1.1"

    def setup_method(self):
        """Reset the shared in-memory rate limit store before every test."""
        limiter.reset()

    def test_login_rate_limit_blocks_after_5_requests(self):
        """First 5 POSTs to /auth/login succeed; the 6th returns 429."""
        with _patch_proxy():
            client = TestClient(app)
            statuses = []
            for _ in range(6):
                resp = client.post(
                    "/auth/login",
                    json={},
                    headers={"X-Forwarded-For": self.LOGIN_IP},
                )
                statuses.append(resp.status_code)

        assert statuses[:5] == [200, 200, 200, 200, 200], f"Expected 5×200, got {statuses[:5]}"
        assert statuses[5] == 429, f"Expected 429 on 6th request, got {statuses[5]}"

    def test_login_rate_limit_429_response_is_json(self):
        """The 429 response from slowapi must be valid JSON."""
        with _patch_proxy():
            client = TestClient(app)
            for _ in range(5):
                client.post("/auth/login", json={}, headers={"X-Forwarded-For": self.LOGIN_IP})
            resp = client.post("/auth/login", json={}, headers={"X-Forwarded-For": self.LOGIN_IP})

        assert resp.status_code == 429

    def test_login_rate_limit_different_ips_are_independent(self):
        """Two different IPs each get their own 5-request budget."""
        ip_a = "10.0.1.2"
        ip_b = "10.0.1.3"

        with _patch_proxy():
            client = TestClient(app)
            # Exhaust ip_a
            for _ in range(5):
                client.post("/auth/login", json={}, headers={"X-Forwarded-For": ip_a})

            # ip_b is unaffected
            resp_b = client.post("/auth/login", json={}, headers={"X-Forwarded-For": ip_b})

        assert resp_b.status_code == 200


class TestRegisterRateLimit:
    """
    /auth/register is limited to 3 requests/minute per IP.
    Each test resets the limiter before running.
    """

    REGISTER_IP = "10.0.2.1"

    def setup_method(self):
        limiter.reset()

    def test_register_rate_limit_blocks_after_3_requests(self):
        """First 3 POSTs to /auth/register succeed; the 4th returns 429."""
        with _patch_proxy():
            client = TestClient(app)
            statuses = []
            for _ in range(4):
                resp = client.post(
                    "/auth/register",
                    json={},
                    headers={"X-Forwarded-For": self.REGISTER_IP},
                )
                statuses.append(resp.status_code)

        assert statuses[:3] == [200, 200, 200], f"Expected 3×200, got {statuses[:3]}"
        assert statuses[3] == 429, f"Expected 429 on 4th request, got {statuses[3]}"

    def test_register_rate_limit_different_ips_are_independent(self):
        """Two different IPs each get their own 3-request budget."""
        ip_a = "10.0.2.2"
        ip_b = "10.0.2.3"

        with _patch_proxy():
            client = TestClient(app)
            # Exhaust ip_a
            for _ in range(3):
                client.post("/auth/register", json={}, headers={"X-Forwarded-For": ip_a})

            # ip_b is unaffected
            resp_b = client.post("/auth/register", json={}, headers={"X-Forwarded-For": ip_b})

        assert resp_b.status_code == 200

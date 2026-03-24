"""
Tests for validate_token JWT validation logic in src/api/auth.py.

These tests are fully deterministic: no network calls, no real .env file, no
real clock — only the fixed test SECRET_KEY injected by conftest.py.

The function under test:

    def validate_token(request: Request) -> dict:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Missing access token")
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

Cookie name  : access_token
Algorithm    : HS256
Secret key   : read from settings.secret_key (env var SECRET_KEY)
On success   : returns the decoded payload dict
On failure   : raises HTTPException with status_code=401
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException

from src.api.auth import validate_token

# The test secret must match what conftest.py injects via os.environ.setdefault.
TEST_SECRET = "test-secret-key-for-unit-tests-only"
ALGORITHM = "HS256"

# "now" for valid tokens: use the real clock so tokens are always fresh.
# For expired tokens we use a frozen past timestamp so they are deterministically
# expired regardless of when the test suite runs.
_NOW = datetime.now(timezone.utc)

# A fixed past timestamp used only when crafting tokens that must be expired.
_PAST = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(token: str | None) -> MagicMock:
    """Return a mock FastAPI Request whose cookies contain *token* (or none)."""
    request = MagicMock()
    if token is None:
        request.cookies = {}
    else:
        request.cookies = {"access_token": token}
    return request


def _make_token(payload: dict, secret: str = TEST_SECRET) -> str:
    """Encode *payload* as a signed HS256 JWT using *secret*."""
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_token() -> str:
    """A valid, non-expired JWT with sub='user-42' and a 1-hour expiry."""
    return _make_token(
        {
            "sub": "user-42",
            "exp": _NOW + timedelta(hours=1),
            "iat": _NOW,
        }
    )


@pytest.fixture
def expired_token() -> str:
    """A JWT whose exp is in the past — always raises ExpiredSignatureError."""
    return _make_token(
        {
            "sub": "user-42",
            "exp": _PAST + timedelta(hours=1),
            "iat": _PAST,
        }
    )


@pytest.fixture
def wrong_secret_token() -> str:
    """A JWT signed with a different secret — always raises InvalidSignatureError."""
    return _make_token(
        {
            "sub": "user-42",
            "exp": _NOW + timedelta(hours=1),
            "iat": _NOW,
        },
        secret="completely-different-secret",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidTokenReturnsPayload:
    """validate_token returns the decoded payload dict for a valid JWT."""

    def test_valid_token_returns_sub_claim(self, valid_token):
        """A valid token in the cookie should return the payload with sub."""
        request = _make_request(valid_token)

        payload = validate_token(request)

        assert payload["sub"] == "user-42"

    def test_valid_token_returns_full_payload(self, valid_token):
        """The returned dict must include all claims present in the token."""
        request = _make_request(valid_token)

        payload = validate_token(request)

        assert "sub" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_valid_token_with_extra_claims_returns_all_claims(self):
        """Additional custom claims are preserved in the returned payload."""
        token = _make_token(
            {
                "sub": "user-99",
                "exp": _NOW + timedelta(hours=1),
                "iat": _NOW,
                "email": "user@example.com",
                "role": "admin",
            }
        )
        request = _make_request(token)

        payload = validate_token(request)

        assert payload["sub"] == "user-99"
        assert payload["email"] == "user@example.com"
        assert payload["role"] == "admin"

    def test_valid_token_return_type_is_dict(self, valid_token):
        """validate_token must return a plain dict, not any wrapper type."""
        request = _make_request(valid_token)

        payload = validate_token(request)

        assert isinstance(payload, dict)


# ---------------------------------------------------------------------------
# Missing / empty cookie
# ---------------------------------------------------------------------------


class TestMissingCookieRaises401:
    """validate_token raises 401 when the access_token cookie is absent."""

    def test_no_cookie_raises_http_401(self):
        """No access_token cookie at all → 401 with 'Missing access token'."""
        request = _make_request(None)

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing access token"

    def test_empty_string_cookie_raises_http_401(self):
        """An empty string value for access_token is treated as missing → 401."""
        request = _make_request("")

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing access token"


# ---------------------------------------------------------------------------
# Expired token
# ---------------------------------------------------------------------------


class TestExpiredTokenRaises401:
    """validate_token raises 401 for tokens whose exp is in the past."""

    def test_expired_token_raises_http_401(self, expired_token):
        """A token with exp in the past must raise 401 with 'Token expired'."""
        request = _make_request(expired_token)

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token expired"


# ---------------------------------------------------------------------------
# Invalid signature
# ---------------------------------------------------------------------------


class TestInvalidSignatureRaises401:
    """validate_token raises 401 when the token was signed with a wrong key."""

    def test_wrong_secret_raises_http_401(self, wrong_secret_token):
        """A token signed with a different secret must raise 401 with 'Invalid token'."""
        request = _make_request(wrong_secret_token)

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"


# ---------------------------------------------------------------------------
# Malformed token
# ---------------------------------------------------------------------------


class TestMalformedTokenRaises401:
    """validate_token raises 401 for strings that are not valid JWTs."""

    def test_random_string_raises_http_401(self):
        """A random non-JWT string must raise 401 with 'Invalid token'."""
        request = _make_request("this-is-not-a-jwt")

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

    def test_partial_jwt_raises_http_401(self):
        """A string with only header.payload (missing signature) must raise 401."""
        # Build a proper token then strip the signature segment.
        full_token = _make_token({"sub": "x", "exp": _NOW + timedelta(hours=1)})
        parts = full_token.split(".")
        truncated = ".".join(parts[:2])  # header.payload — no signature

        request = _make_request(truncated)

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

    def test_jwt_with_tampered_payload_raises_http_401(self):
        """Replacing the payload segment with garbage must raise 401."""
        import base64

        full_token = _make_token({"sub": "x", "exp": _NOW + timedelta(hours=1)})
        header, _payload, signature = full_token.split(".")

        # Replace the payload with something that decodes to different data.
        garbage_payload = base64.urlsafe_b64encode(b'{"sub":"hacker"}').rstrip(b"=").decode()
        tampered = f"{header}.{garbage_payload}.{signature}"

        request = _make_request(tampered)

        with pytest.raises(HTTPException) as exc_info:
            validate_token(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

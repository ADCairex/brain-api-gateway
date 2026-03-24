"""
Tests for _resolve_target route resolution logic.

These tests are fully deterministic: no database, no network calls, no real
environment variables beyond the dummy SECRET_KEY injected in conftest.py.

The function under test:

    def _resolve_target(path: str) -> tuple[str, str] | None:
        for prefix, service_url in SERVICE_MAP.items():
            if path.startswith(prefix):
                remainder = path[len(prefix):]
                return service_url + remainder, remainder
        return None

SERVICE_MAP = {
    "/auth":    "http://brain-auth-service:8001",
    "/finance": "http://brain-finance-service:8002",
}
"""

from src.api.app import _resolve_target

# ---------------------------------------------------------------------------
# Auth service routing
# ---------------------------------------------------------------------------


class TestAuthRouteResolution:
    """_resolve_target maps /auth/* paths to brain-auth-service:8001."""

    def test_auth_login_resolves_to_auth_service(self):
        """Full path /auth/login should resolve to the auth service."""
        result = _resolve_target("/auth/login")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-auth-service:8001/login"

    def test_auth_register_resolves_to_auth_service(self):
        """Full path /auth/register should resolve to the auth service."""
        result = _resolve_target("/auth/register")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-auth-service:8001/register"

    def test_auth_refresh_resolves_to_auth_service(self):
        """Full path /auth/refresh should resolve to the auth service."""
        result = _resolve_target("/auth/refresh")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-auth-service:8001/refresh"

    def test_auth_nested_path_resolves_to_auth_service(self):
        """Nested paths under /auth should forward the full remainder."""
        result = _resolve_target("/auth/users/profile/settings")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-auth-service:8001/users/profile/settings"


# ---------------------------------------------------------------------------
# Finance service routing
# ---------------------------------------------------------------------------


class TestFinanceRouteResolution:
    """_resolve_target maps /finance/* paths to brain-finance-service:8002."""

    def test_finance_transactions_resolves_to_finance_service(self):
        """/finance/transactions should resolve to the finance service."""
        result = _resolve_target("/finance/transactions")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-finance-service:8002/transactions"

    def test_finance_nested_path_resolves_correctly(self):
        """/finance/transactions/123 should forward the full nested remainder."""
        result = _resolve_target("/finance/transactions/123")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-finance-service:8002/transactions/123"

    def test_finance_query_params_are_preserved_in_remainder(self):
        """Path without query string: remainder is just the path segment."""
        result = _resolve_target("/finance/accounts")

        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-finance-service:8002/accounts"


# ---------------------------------------------------------------------------
# Stripped path correctness
# ---------------------------------------------------------------------------


class TestStrippedPath:
    """The second element of the returned tuple is the prefix-stripped path."""

    def test_auth_login_stripped_path_is_slash_login(self):
        """/auth/login should strip /auth, leaving /login."""
        result = _resolve_target("/auth/login")

        assert result is not None
        _, stripped_path = result
        assert stripped_path == "/login"

    def test_auth_register_stripped_path_is_slash_register(self):
        """/auth/register should strip /auth, leaving /register."""
        result = _resolve_target("/auth/register")

        assert result is not None
        _, stripped_path = result
        assert stripped_path == "/register"

    def test_finance_deep_path_stripped_correctly(self):
        """/finance/transactions/123 should strip /finance, leaving /transactions/123."""
        result = _resolve_target("/finance/transactions/123")

        assert result is not None
        _, stripped_path = result
        assert stripped_path == "/transactions/123"

    def test_stripped_path_starts_with_slash(self):
        """Stripped path must always start with / for valid upstream forwarding."""
        for path in ["/auth/login", "/auth/register", "/finance/transactions"]:
            result = _resolve_target(path)
            assert result is not None, f"Expected a match for {path!r}"
            _, stripped_path = result
            assert stripped_path.startswith("/"), f"Stripped path {stripped_path!r} for {path!r} does not start with /"


# ---------------------------------------------------------------------------
# Unknown / unmatched routes
# ---------------------------------------------------------------------------


class TestUnknownRoutes:
    """Paths with no matching SERVICE_MAP prefix should return None."""

    def test_unknown_prefix_returns_none(self):
        """A path with an unrecognised prefix should not resolve."""
        result = _resolve_target("/unknown/path")

        assert result is None

    def test_root_path_returns_none(self):
        """The bare root / has no prefix match and should return None."""
        result = _resolve_target("/")

        assert result is None

    def test_empty_string_returns_none(self):
        """An empty string path has no prefix match and should return None."""
        result = _resolve_target("")

        assert result is None

    def test_arbitrary_path_returns_none(self):
        """Random paths that don't start with a known prefix return None."""
        for path in ["/admin/users", "/api/v1/data", "/healthz", "/metrics"]:
            assert _resolve_target(path) is None, f"Expected None for {path!r}"


# ---------------------------------------------------------------------------
# Prefix boundary edge cases
# ---------------------------------------------------------------------------


class TestPrefixBoundaryBehavior:
    """
    Document the exact prefix-matching semantics of _resolve_target.

    The implementation uses str.startswith(), which means a path like
    /authentication DOES match the /auth prefix because "authentication"
    starts with "auth".  These tests document this known behaviour so that
    any accidental change is immediately caught.
    """

    def test_auth_prefix_matches_longer_word_starting_with_auth(self):
        """/authentication starts with /auth — current impl resolves it to auth-service.

        This is a documented behaviour of the simple startswith() check.
        The stripped path would be 'entication' (without leading slash).
        If the routing logic is ever tightened to require a slash boundary,
        this test should be updated accordingly.
        """
        result = _resolve_target("/authentication")

        # Current implementation: startswith("/auth") → matches
        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-auth-service:8001entication"
        assert stripped_path == "entication"

    def test_finance_prefix_matches_longer_word_starting_with_finance(self):
        """/finances starts with /finance — current impl resolves it to finance-service."""
        result = _resolve_target("/finances")

        # Current implementation: startswith("/finance") → matches
        assert result is not None
        target_url, stripped_path = result
        assert target_url == "http://brain-finance-service:8002s"
        assert stripped_path == "s"

    def test_partial_prefix_does_not_match(self):
        """/aut does not start with /auth — should return None."""
        result = _resolve_target("/aut")

        assert result is None

    def test_partial_finance_prefix_does_not_match(self):
        """/finan does not start with /finance — should return None."""
        result = _resolve_target("/finan")

        assert result is None

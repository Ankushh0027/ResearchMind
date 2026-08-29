"""Unit tests for Phase 6.5 API-key authentication.

Coverage:
1.  validate_api_key_constant_time — correct match
2.  validate_api_key_constant_time — incorrect key
3.  validate_api_key_constant_time — empty provided key
4.  validate_api_key_constant_time — empty expected key
5.  validate_api_key_constant_time — both empty
6.  verify_api_key skips check when API_AUTH_ENABLED=False
7.  verify_api_key raises 401 — missing credentials (auth enabled)
8.  verify_api_key raises 401 — invalid Bearer token (auth enabled)
9.  verify_api_key raises 401 — wrong X-API-Key header (auth enabled)
10. verify_api_key passes — correct Bearer token (auth enabled)
11. verify_api_key passes — correct X-API-Key header (auth enabled)
12. 401 response body does not contain the raw API key
13. Constant-time comparison is used (secrets.compare_digest integration)
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.orchestration.router import create_default_worker_router
from app.security.auth import validate_api_key_constant_time

# ---------------------------------------------------------------------------
# Unit tests: validate_api_key_constant_time
# ---------------------------------------------------------------------------


class TestValidateApiKeyConstantTime:
    """Tests for the raw constant-time comparison helper."""

    def test_matching_keys_return_true(self) -> None:
        assert validate_api_key_constant_time("abc123", "abc123") is True

    def test_mismatched_keys_return_false(self) -> None:
        assert validate_api_key_constant_time("abc123", "wrong") is False

    def test_empty_provided_key_returns_false(self) -> None:
        assert validate_api_key_constant_time("", "expected") is False

    def test_empty_expected_key_returns_false(self) -> None:
        assert validate_api_key_constant_time("provided", "") is False

    def test_both_empty_returns_false(self) -> None:
        # Even empty vs empty should return False — no key means no access.
        assert validate_api_key_constant_time("", "") is False

    def test_prefix_match_is_not_sufficient(self) -> None:
        # A common-prefix attack must not succeed.
        assert validate_api_key_constant_time("abc", "abcXXX") is False

    def test_unicode_keys_handled(self) -> None:
        key = "секрет_токен_üñíçödé"
        assert validate_api_key_constant_time(key, key) is True

    def test_constant_time_uses_secrets_compare_digest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that secrets.compare_digest is called (not a direct == comparison)."""
        import secrets

        calls: list[tuple[bytes, bytes]] = []

        original = secrets.compare_digest

        def recording_compare_digest(a: bytes, b: bytes) -> bool:
            calls.append((a, b))
            return original(a, b)

        monkeypatch.setattr(secrets, "compare_digest", recording_compare_digest)

        validate_api_key_constant_time("test_key", "test_key")
        assert len(calls) >= 1, "secrets.compare_digest was not called"


# ---------------------------------------------------------------------------
# Integration-style tests: verify_api_key FastAPI dependency
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    api_auth_enabled: bool = True,
    api_key: str = "test-secret-key-1234",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure the environment so AppSettings returns desired values."""
    monkeypatch.setenv("API_AUTH_ENABLED", str(api_auth_enabled).lower())
    monkeypatch.setenv("API_KEY", api_key)
    # Clear the settings LRU cache so the test isolation takes effect
    from app.config.settings import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Always clear the settings cache before and after each test."""
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_authed_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Return a FastAPI app configured with auth enabled."""
    _make_settings(
        api_auth_enabled=True, api_key="super-secret", monkeypatch=monkeypatch
    )
    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    return create_app(service=service)


@pytest.mark.asyncio
async def test_auth_disabled_allows_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """When API_AUTH_ENABLED=false, /api/v1/runs accepts requests without credentials."""
    _make_settings(api_auth_enabled=False, monkeypatch=monkeypatch)
    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test query for auth disabled"},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_auth_missing_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing credentials with auth enabled → HTTP 401."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test query"},
        )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] == "UNAUTHORIZED"
    # The raw API key must NOT appear in the response body
    assert "super-secret" not in resp.text


@pytest.mark.asyncio
async def test_auth_invalid_bearer_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid Bearer token with auth enabled → HTTP 401."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test query"},
            headers={"Authorization": "Bearer wrong-key"},
        )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] == "UNAUTHORIZED"
    # The wrong key must NOT be echoed back
    assert "wrong-key" not in resp.text
    # The real key must NOT appear
    assert "super-secret" not in resp.text


@pytest.mark.asyncio
async def test_auth_valid_bearer_returns_201(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid Bearer token with auth enabled → HTTP 201."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "valid request with correct key"},
            headers={"Authorization": "Bearer super-secret"},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_auth_valid_x_api_key_header_returns_201(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid X-API-Key fallback header → HTTP 201."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test using X-API-Key fallback header"},
            headers={"X-API-Key": "super-secret"},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_health_endpoint_accessible_without_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health endpoint is publicly accessible even when auth is enabled."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_401_response_does_not_leak_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure no part of the 401 error body contains the configured API key."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test"},
            headers={"Authorization": "Bearer bad-key"},
        )
    assert "super-secret" not in resp.text
    assert "API_KEY" not in resp.text


@pytest.mark.asyncio
async def test_invalid_x_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong X-API-Key value → HTTP 401."""
    app = _make_authed_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test"},
            headers={"X-API-Key": "totally-wrong"},
        )
    assert resp.status_code == 401

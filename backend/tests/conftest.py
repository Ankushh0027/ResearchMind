"""Global pytest configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests run in an isolated test environment without requiring real secrets."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-gcp-project")
    # Phase 6.5: disable auth and rate limiting by default so existing tests
    # remain deterministic without needing credentials.
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    # Clear the settings LRU cache so each test starts clean.
    from app.config.settings import get_settings

    get_settings.cache_clear()

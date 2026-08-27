"""Unit tests for SSRF protection and outbound URL validation."""

import pytest

from app.security.ssrf import (
    BLOCKED_HOSTNAMES,
    SSRFProtectionError,
    validate_url_safety,
)


class TestSSRFProtection:
    """Test suite verifying SSRF URL safety validation boundaries."""

    @pytest.mark.parametrize(
        "safe_url",
        [
            "https://example.com",
            "https://api.tavily.com/search",
            "https://export.arxiv.org/api/query",
            "http://news.ycombinator.com/item?id=123",
            "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "https://github.com/Ankushh0027/ResearchMind",
        ],
    )
    def test_safe_public_urls_allowed(self, safe_url: str) -> None:
        """Valid public URLs must pass validation without error."""
        validate_url_safety(safe_url)

    @pytest.mark.parametrize(
        "blocked_url",
        [
            "http://localhost",
            "http://localhost:8080/admin",
            "http://127.0.0.1",
            "http://127.0.0.1:6333",
            "http://0.0.0.0:8000",
            "http://[::1]:8080",
            "http://subdomain.localhost",
            "http://metadata.google.internal/computeMetadata/v1",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.1",
            "http://10.255.255.254/secret",
            "http://172.16.0.1:9000",
            "http://172.31.255.255",
            "http://192.168.1.1/router",
            "http://192.168.0.254",
            "http://169.254.0.1/linklocal",
        ],
    )
    def test_internal_and_loopback_urls_blocked(self, blocked_url: str) -> None:
        """Loopback, private RFC1918, link-local, and cloud metadata URLs must be rejected."""
        with pytest.raises(SSRFProtectionError) as exc_info:
            validate_url_safety(blocked_url)
        assert (
            "blocked" in str(exc_info.value).lower()
            or "prohibited" in str(exc_info.value).lower()
        )

    @pytest.mark.parametrize(
        "invalid_url",
        [
            "",
            "   ",
            "ftp://files.example.com/test.txt",
            "file:///etc/passwd",
            "gcs://bucket/object",
            "javascript:alert(1)",
            "data:text/html,<h1>hello</h1>",
            "http://",
            "https://:8080",
        ],
    )
    def test_invalid_and_non_http_schemes_rejected(self, invalid_url: str) -> None:
        """Non-HTTP/HTTPS schemes and empty or malformed URLs must raise SSRFProtectionError."""
        with pytest.raises(SSRFProtectionError):
            validate_url_safety(invalid_url)

    def test_blocked_hostnames_constant(self) -> None:
        """Ensure canonical blocked hostnames are in the blacklist."""
        assert "localhost" in BLOCKED_HOSTNAMES
        assert "127.0.0.1" in BLOCKED_HOSTNAMES
        assert "169.254.169.254" in BLOCKED_HOSTNAMES
        assert "metadata.google.internal" in BLOCKED_HOSTNAMES

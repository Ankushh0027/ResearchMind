"""Server-Side Request Forgery (SSRF) protection and URL validation utilities."""

import ipaddress
import urllib.parse
from typing import Any

from app.common.errors import ResearchMindError


class SSRFProtectionError(ResearchMindError):
    """Raised when an outbound URL violates SSRF safety constraints."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)


BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "::",
        "metadata.google.internal",
        "metadata.internal",
        "169.254.169.254",
        "instance-data",
    }
)


def validate_url_safety(
    url: str,
    allowed_schemes: tuple[str, ...] = ("http", "https"),
) -> None:
    """Validate that a URL does not target localhost, private, link-local, or cloud metadata endpoints.

    Raises:
        SSRFProtectionError: If the URL is malformed, uses an unsupported scheme,
                             or resolves to a prohibited network boundary.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise SSRFProtectionError("Target URL must not be empty or whitespace only")

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception as e:
        raise SSRFProtectionError(f"Failed to parse URL '{url}': {e}") from e

    scheme = (parsed.scheme or "").lower()
    if scheme not in allowed_schemes:
        raise SSRFProtectionError(
            f"Prohibited URL scheme '{scheme}'. Only {allowed_schemes} are permitted.",
            {"url": url, "scheme": scheme},
        )

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise SSRFProtectionError(
            "URL must contain a valid hostname.",
            {"url": url},
        )

    # 1. Exact blocked hostname matching
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise SSRFProtectionError(
            f"Access to prohibited hostname '{hostname}' is blocked.",
            {"url": url, "hostname": hostname},
        )

    # 2. IP address literal checks
    try:
        ip = ipaddress.ip_address(hostname)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SSRFProtectionError(
                f"Access to private, loopback, or link-local IP '{hostname}' is blocked.",
                {"url": url, "ip": str(ip)},
            )
    except ValueError:
        # Not a raw IP literal; hostname is a standard domain name
        pass


__all__ = [
    "BLOCKED_HOSTNAMES",
    "SSRFProtectionError",
    "validate_url_safety",
]

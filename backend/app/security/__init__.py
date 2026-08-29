"""Security policies, role permission matrices, untrusted content boundaries, and SSRF validation.

Phase 6.5 additions: API-key authentication, sliding-window rate limiting,
security headers middleware, and request-size protection.
"""

from app.security.auth import (
    validate_api_key_constant_time,
    verify_api_key,
)
from app.security.boundary import (
    ContentBoundarySanitizer,
    UntrustedContentEnvelope,
)
from app.security.headers import SecurityHeadersMiddleware
from app.security.permissions import (
    ROLE_TOOL_PERMISSIONS,
    SecurityPolicy,
)
from app.security.rate_limiter import (
    InMemoryRateLimiter,
    RateLimiterProtocol,
    get_rate_limiter,
    rate_limit_submissions,
    set_rate_limiter,
)
from app.security.request_size import RequestSizeLimitMiddleware
from app.security.ssrf import (
    BLOCKED_HOSTNAMES,
    SSRFProtectionError,
    validate_url_safety,
)

__all__ = [
    "BLOCKED_HOSTNAMES",
    "ContentBoundarySanitizer",
    "InMemoryRateLimiter",
    "RateLimiterProtocol",
    "ROLE_TOOL_PERMISSIONS",
    "RequestSizeLimitMiddleware",
    "SSRFProtectionError",
    "SecurityHeadersMiddleware",
    "SecurityPolicy",
    "UntrustedContentEnvelope",
    "get_rate_limiter",
    "rate_limit_submissions",
    "set_rate_limiter",
    "validate_api_key_constant_time",
    "validate_url_safety",
    "verify_api_key",
]

"""Security policies, role permission matrices, untrusted content boundaries,
API-key authentication, tenant resolution, rate limiting, and security audit logging.
"""

from app.security.audit import (
    SecurityAuditEvent,
    SecurityEventType,
    log_security_event,
    sanitize_audit_details,
)
from app.security.auth import (
    TenantContext,
    compute_key_digest,
    get_current_tenant,
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
    "ROLE_TOOL_PERMISSIONS",
    "RateLimiterProtocol",
    "RequestSizeLimitMiddleware",
    "SSRFProtectionError",
    "SecurityAuditEvent",
    "SecurityHeadersMiddleware",
    "SecurityPolicy",
    "SecurityEventType",
    "TenantContext",
    "UntrustedContentEnvelope",
    "compute_key_digest",
    "get_current_tenant",
    "get_rate_limiter",
    "log_security_event",
    "rate_limit_submissions",
    "sanitize_audit_details",
    "set_rate_limiter",
    "validate_api_key_constant_time",
    "validate_url_safety",
    "verify_api_key",
]

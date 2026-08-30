"""Security audit logging module for ResearchMind API security and compliance.

Design principles:
- Emits structured JSON security audit events.
- Never logs API keys, tokens, Authorization headers, or password credentials.
- Includes safe contextual identifiers: timestamp, event_type, tenant_id, request_id,
  client_ip, path, method, and status_code.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("app.security.audit")


class SecurityEventType(StrEnum):
    """Classification of security-relevant audit events."""

    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    CROSS_TENANT_ACCESS_DENIED = "CROSS_TENANT_ACCESS_DENIED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    SUSPICIOUS_REQUEST = "SUSPICIOUS_REQUEST"
    SSRF_BLOCKED = "SSRF_BLOCKED"


class SecurityAuditEvent(BaseModel):
    """Structured record for a security-relevant event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: SecurityEventType = Field(..., description="Category of security event")
    tenant_id: str | None = Field(
        default=None, description="Resolved tenant identifier if known"
    )
    request_id: str | None = Field(
        default=None, description="Trace or correlation request identifier"
    )
    client_ip: str | None = Field(
        default=None, description="Client IP address (X-Forwarded-For or direct)"
    )
    path: str = Field(..., description="Target request path")
    method: str = Field(..., description="HTTP method")
    status_code: int = Field(..., description="Resulting HTTP status code")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Safe non-sensitive metadata"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp",
    )


def sanitize_audit_details(details: dict[str, Any]) -> dict[str, Any]:
    """Sanitize arbitrary key-value metadata to prevent secret leakage in audit logs."""
    sensitive_keys = {
        "api_key",
        "authorization",
        "bearer",
        "secret",
        "password",
        "token",
        "credentials",
        "x-api-key",
    }
    clean: dict[str, Any] = {}
    for key, value in details.items():
        key_lower = str(key).lower()
        if any(s_key in key_lower for s_key in sensitive_keys):
            clean[key] = "[REDACTED]"
        else:
            clean[key] = value
    return clean


def log_security_event(
    event_type: SecurityEventType,
    path: str,
    method: str,
    status_code: int,
    tenant_id: str | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Construct and log a structured security audit event at WARNING level.

    Guarantees no raw secrets are present in logger output.
    """
    clean_details = sanitize_audit_details(details or {})
    event = SecurityAuditEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        request_id=request_id,
        client_ip=client_ip,
        path=path,
        method=method,
        status_code=status_code,
        details=clean_details,
    )

    logger.warning(
        "SECURITY_AUDIT_EVENT: %s",
        event.model_dump_json(),
        extra={"audit_event": event.model_dump()},
    )
    return event


__all__ = [
    "SecurityAuditEvent",
    "SecurityEventType",
    "log_security_event",
    "sanitize_audit_details",
]

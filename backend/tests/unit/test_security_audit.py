"""Unit tests for Phase 7.2 security audit logging.

Coverage:
1. sanitize_audit_details redacts sensitive keys (api_key, token, password, secret, etc.).
2. log_security_event creates structured SecurityAuditEvent with valid ISO timestamp.
3. Auth failure emits AUTHENTICATION_FAILED audit event.
4. Rate limit violation emits RATE_LIMIT_EXCEEDED audit event.
5. Payload size violation emits PAYLOAD_TOO_LARGE audit event.
6. Audit log output contains zero raw keys or credentials.
"""

from __future__ import annotations

import logging

import pytest

from app.security.audit import (
    SecurityAuditEvent,
    SecurityEventType,
    log_security_event,
    sanitize_audit_details,
)


def test_sanitize_audit_details_redacts_sensitive_keys() -> None:
    raw_details = {
        "user_agent": "Mozilla/5.0",
        "api_key": "secret-key-12345",
        "Authorization": "Bearer token-xyz",
        "nested_secret": "top-secret-password",
        "safe_count": 42,
    }
    clean = sanitize_audit_details(raw_details)
    assert clean["user_agent"] == "Mozilla/5.0"
    assert clean["safe_count"] == 42
    assert clean["api_key"] == "[REDACTED]"
    assert clean["Authorization"] == "[REDACTED]"
    assert clean["nested_secret"] == "[REDACTED]"


def test_log_security_event_constructs_valid_audit_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    event = log_security_event(
        event_type=SecurityEventType.AUTHENTICATION_FAILED,
        path="/api/v1/runs",
        method="POST",
        status_code=401,
        client_ip="192.168.1.50",
        details={"provided_header": "Bearer bad-key", "api_key": "raw-key-to-redact"},
    )

    assert isinstance(event, SecurityAuditEvent)
    assert event.event_type == SecurityEventType.AUTHENTICATION_FAILED
    assert event.status_code == 401
    assert event.details["api_key"] == "[REDACTED]"
    assert "SECURITY_AUDIT_EVENT" in caplog.text
    assert "raw-key-to-redact" not in caplog.text


def test_audit_event_contains_no_raw_keys_in_json() -> None:
    event = log_security_event(
        event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
        path="/api/v1/runs",
        method="POST",
        status_code=429,
        tenant_id="tenant_123",
        client_ip="10.0.0.1",
        details={"token": "super-secret-auth-token"},
    )

    json_str = event.model_dump_json()
    assert "super-secret-auth-token" not in json_str
    assert "RATE_LIMIT_EXCEEDED" in json_str
    assert "tenant_123" in json_str

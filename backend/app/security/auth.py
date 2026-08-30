"""API-key authentication and multi-tenant context resolution for FastAPI endpoints.

Design notes:
- API keys are NEVER stored or logged in plaintext. Server-side configuration stores
  pre-computed SHA-256 digests.
- Incoming caller keys are hashed on receipt (`hashlib.sha256`) and compared against
  configured key digests using `hmac.compare_digest` in constant time.
- Supports single API key (`settings.api_key`) and multiple configured keys
  with tenant mapping (`settings.api_keys_json`).
- When `API_AUTH_ENABLED` is `False` (default for dev/tests), defaults to
  `TenantContext(tenant_id="default-tenant")`.
- Preferred header: `Authorization: Bearer <API_KEY>`
  Fallback header:  `X-API-Key: <API_KEY>`
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import AppSettings, get_settings
from app.security.audit import SecurityEventType, log_security_event

logger = logging.getLogger(__name__)

# HTTPBearer extracts the Bearer token from the Authorization header.
# auto_error=False lets us return a structured 401 instead of the default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TenantContext:
    """Authenticated tenant and caller identity container."""

    tenant_id: str = "default-tenant"
    key_id: str | None = None


def compute_key_digest(key: str) -> bytes:
    """Compute a SHA-256 digest of a raw key string.

    Args:
        key: Plaintext API key string.

    Returns:
        32-byte SHA-256 binary digest.
    """
    if not key:
        return hashlib.sha256(b"").digest()
    return hashlib.sha256(key.encode("utf-8")).digest()


def validate_api_key_constant_time(provided_key: str, expected_key: str) -> bool:
    """Compare two API keys in constant time by comparing their SHA-256 digests.

    Uses :func:`hmac.compare_digest` over fixed-length digests to prevent timing attacks.

    Args:
        provided_key: The key supplied by the API caller.
        expected_key: The configured server-side key.

    Returns:
        ``True`` if the keys match, ``False`` otherwise.
    """
    if not provided_key or not expected_key:
        # Perform a dummy digest comparison to preserve constant-time execution profile
        hmac.compare_digest(
            hashlib.sha256(b"a").digest(), hashlib.sha256(b"b").digest()
        )
        return False

    provided_digest = compute_key_digest(provided_key)
    expected_digest = compute_key_digest(expected_key)
    return hmac.compare_digest(provided_digest, expected_digest)


def _load_configured_key_digests(settings: AppSettings) -> dict[bytes, TenantContext]:
    """Parse configured API keys into a digest -> TenantContext mapping.

    Supports:
    1. Multiple keys in ``API_KEYS_JSON`` e.g.
       `{"key1": "tenant-alpha", "key2": {"tenant_id": "tenant-beta", "key_id": "k2"}}`
       or JSON list `[{"key": "key1", "tenant_id": "tenant-alpha"}, ...]`
    2. Single key in ``API_KEY`` defaulting to tenant_id="default-tenant".
    """
    key_map: dict[bytes, TenantContext] = {}

    # 1. Parse API_KEYS_JSON if present
    if settings.api_keys_json:
        try:
            parsed = json.loads(settings.api_keys_json)
            if isinstance(parsed, dict):
                for k, val in parsed.items():
                    if not k:
                        continue
                    digest = compute_key_digest(str(k))
                    if isinstance(val, str):
                        key_map[digest] = TenantContext(tenant_id=val, key_id=None)
                    elif isinstance(val, dict):
                        t_id = str(val.get("tenant_id", "default-tenant"))
                        k_id = val.get("key_id")
                        key_map[digest] = TenantContext(
                            tenant_id=t_id, key_id=str(k_id) if k_id else None
                        )
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "key" in item:
                        k = str(item["key"])
                        if not k:
                            continue
                        digest = compute_key_digest(k)
                        t_id = str(item.get("tenant_id", "default-tenant"))
                        k_id = item.get("key_id")
                        key_map[digest] = TenantContext(
                            tenant_id=t_id, key_id=str(k_id) if k_id else None
                        )
        except Exception as e:
            logger.warning("Failed to parse API_KEYS_JSON configuration: %s", e)

    # 2. Fallback single key in API_KEY
    if settings.api_key:
        single_digest = compute_key_digest(settings.api_key)
        if single_digest not in key_map:
            key_map[single_digest] = TenantContext(
                tenant_id="default-tenant", key_id="primary"
            )

    return key_map


def _resolve_tenant_from_key(
    provided_key: str, settings: AppSettings
) -> TenantContext | None:
    """Resolve caller identity from provided API key using constant-time digest comparison."""
    if not provided_key:
        return None

    provided_digest = compute_key_digest(provided_key)
    configured_map = _load_configured_key_digests(settings)

    matched_tenant: TenantContext | None = None

    # Perform constant time check over all configured key digests
    for digest, tenant in configured_map.items():
        if hmac.compare_digest(provided_digest, digest):
            matched_tenant = tenant

    return matched_tenant


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def get_current_tenant(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: AppSettings = Depends(get_settings),
) -> TenantContext:
    """FastAPI dependency resolving and enforcing authenticated tenant identity.

    When ``API_AUTH_ENABLED`` is ``False`` (default for dev/tests), returns
    ``TenantContext(tenant_id="default-tenant")``.

    When ``API_AUTH_ENABLED`` is ``True``:
    - Extracts key from ``Authorization: Bearer <key>`` or ``X-API-Key``.
    - Verifies key against configured SHA-256 digests in constant time.
    - Attaches resolved tenant to ``request.state.tenant`` and ``request.state.tenant_id``.
    - Emits structured security audit events on authentication failures.
    - Raises HTTP 401 without echoing any secret data.
    """
    if not settings.api_auth_enabled:
        tenant = TenantContext(tenant_id="default-tenant")
        request.state.tenant = tenant
        request.state.tenant_id = tenant.tenant_id
        return tenant

    # Extract provided key
    provided_key: str | None = None
    if credentials is not None:
        provided_key = credentials.credentials
    if not provided_key:
        provided_key = request.headers.get("X-API-Key")

    client_ip = _get_client_ip(request)

    if not provided_key:
        log_security_event(
            event_type=SecurityEventType.AUTHENTICATION_FAILED,
            path=str(request.url.path),
            method=request.method,
            status_code=401,
            client_ip=client_ip,
            details={"reason": "Missing API key credentials"},
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "message": "Authentication required. Provide a valid API key in the Authorization header.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    resolved_tenant = _resolve_tenant_from_key(provided_key, settings)

    if resolved_tenant is None:
        log_security_event(
            event_type=SecurityEventType.AUTHENTICATION_FAILED,
            path=str(request.url.path),
            method=request.method,
            status_code=401,
            client_ip=client_ip,
            details={"reason": "Invalid API key presented"},
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "message": "Invalid API key.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.tenant = resolved_tenant
    request.state.tenant_id = resolved_tenant.tenant_id
    return resolved_tenant


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: AppSettings = Depends(get_settings),
) -> None:
    """FastAPI dependency for API-key verification (delegates to get_current_tenant)."""
    await get_current_tenant(
        request=request, credentials=credentials, settings=settings
    )


__all__ = [
    "TenantContext",
    "compute_key_digest",
    "get_current_tenant",
    "validate_api_key_constant_time",
    "verify_api_key",
]

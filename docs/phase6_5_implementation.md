# ResearchMind Phase 6.5 — API Security, Authentication & Request Protection

## 1. Overview

Phase 6.5 introduces a production-grade, testable API security boundary for ResearchMind. The implementation is scoped to what is appropriate for a hackathon submission day: clean, correct, and credible — without over-engineering.

Components implemented:

| Component | Module | Description |
|---|---|---|
| API-key authentication | `app.security.auth` | Bearer-token validation with constant-time comparison |
| Rate limiting | `app.security.rate_limiter` | Process-local sliding-window limiter with Protocol interface |
| Security headers | `app.security.headers` | ASGI middleware for standard HTTP security headers |
| Request-size guard | `app.security.request_size` | ASGI middleware for early Content-Length rejection |
| Structured error handling | `app.api.app` | JSON exception handlers with no stack trace or secret leakage |
| CORS hardening | `app.api.app` | Restrictive explicit-origin CORS (no wildcard) |

---

## 2. Authentication Flow

```
Client Request
    │
    ├── GET /healthz            ──► No authentication required (public)
    │
    └── /api/v1/*               ──► verify_api_key dependency
            │
            ├── API_AUTH_ENABLED=false   ──► No-op, request passes through
            │
            └── API_AUTH_ENABLED=true
                    │
                    ├── Extract token from: Authorization: Bearer <token>
                    │   Fallback:           X-API-Key: <token>
                    │
                    ├── Token missing?
                    │       └── HTTP 401  {"error_code": "UNAUTHORIZED", ...}
                    │
                    ├── secrets.compare_digest(provided, expected)
                    │
                    ├── Keys do not match?
                    │       └── HTTP 401  {"error_code": "UNAUTHORIZED", ...}
                    │
                    └── Keys match → request continues
```

### Security Properties

- **Constant-time comparison**: `secrets.compare_digest` is used, preventing timing-based oracle attacks where an attacker could infer correct key prefix characters from response timing.
- **No secret logging**: The raw API key is never written to logs or error messages. Authentication failure logs only record the request path and method.
- **No secret echoing**: 401 responses do not echo back the provided key or any fragment of the configured key.
- **Header preference**: `Authorization: Bearer <token>` is the primary header. `X-API-Key: <token>` is supported as a fallback.

---

## 3. Protected vs Public Endpoints

| Endpoint | Method | Authentication Required | Rate Limited |
|---|---|---|---|
| `/healthz` | GET | ❌ Public | ❌ No |
| `/docs` | GET | ❌ Public | ❌ No |
| `/redoc` | GET | ❌ Public | ❌ No |
| `/openapi.json` | GET | ❌ Public | ❌ No |
| `/api/v1/runs` | POST | ✅ Yes (when enabled) | ✅ Yes (when enabled) |
| `/api/v1/runs/{run_id}` | GET | ✅ Yes (when enabled) | ❌ No |
| `/api/v1/runs/{run_id}/cancel` | POST | ✅ Yes (when enabled) | ❌ No |
| `/api/v1/runs/{run_id}/events` | GET | ✅ Yes (when enabled) | ❌ No |

---

## 4. CORS Model

### Configuration

```env
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080,https://app.example.com
```

### Policy

- **No wildcard `*`**: Wildcard origins are disallowed when `allow_credentials=True`. The middleware filters any wildcard from configured origins and emits a warning.
- **Explicit origins only**: Only origins listed in `CORS_ALLOWED_ORIGINS` receive `Access-Control-Allow-Origin` in responses.
- **Allowed methods**: `GET`, `POST`, `OPTIONS`.
- **Allowed headers**: `Authorization`, `Content-Type`, `X-API-Key`.
- **Credentials**: Enabled.

### Local Development

For local development, the default includes:
```
http://localhost:3000
http://localhost:8080
http://127.0.0.1:3000
```

---

## 5. Rate Limiting Model

### Architecture

```
POST /api/v1/runs
        │
        ├── RATE_LIMIT_ENABLED=false   ──► No-op
        │
        └── RATE_LIMIT_ENABLED=true
                │
                ├── Identify client: X-Forwarded-For (first hop) or client IP
                │
                ├── InMemoryRateLimiter.is_allowed(
                │       key=client_ip,
                │       max_requests=RATE_LIMIT_REQUESTS,       # default: 60
                │       window_seconds=RATE_LIMIT_WINDOW_SECONDS # default: 60
                │   )
                │
                ├── Within limit?  ──► Request continues
                │
                └── Exceeded?
                        └── HTTP 429
                            Headers: Retry-After: <window_seconds>
                            Body:    {"error_code": "RATE_LIMIT_EXCEEDED", ...}
```

### In-Memory Sliding Window

`InMemoryRateLimiter` stores a per-client `deque` of monotonic timestamps. On each request:
1. Timestamps older than `window_seconds` are pruned from the front.
2. If the remaining count is ≥ `max_requests`, the request is rejected.
3. Otherwise, the current timestamp is appended.

This achieves a true sliding window (not a fixed-bucket approximation).

### ⚠️ Distributed Deployment Limitation

> **CRITICAL**: The `InMemoryRateLimiter` is PROCESS-LOCAL.
>
> Rate limit state is NOT shared across:
> - Multiple worker processes (uvicorn `--workers N`)
> - Multiple container replicas behind a load balancer
> - Kubernetes pods
>
> **Implication**: In a multi-instance deployment, each instance enforces its own independent limit. A client could send `max_requests × N` requests by distributing them across N instances.
>
> **Mitigation**: Implement `RateLimiterProtocol` with a Redis-backed shared store (e.g., Redis `ZADD`/`ZREMRANGEBYSCORE` pattern) and inject it via `set_rate_limiter()` at application startup. No changes to route handlers are required.

### RateLimiterProtocol Interface

```python
class RateLimiterProtocol(Protocol):
    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool: ...
    def reset(self, key: str | None = None) -> None: ...
```

To replace with Redis:
```python
# In your production startup code:
from app.security.rate_limiter import set_rate_limiter

set_rate_limiter(RedisRateLimiter(redis_client))
```

---

## 6. Request Size Limits

### Body Size (ASGI-level)

`RequestSizeLimitMiddleware` inspects the `Content-Length` header before body parsing begins:

- `Content-Length` > `MAX_REQUEST_BODY_BYTES` → HTTP 413
- `Content-Length` absent → No blocking (content is allowed through)
- Rejection is at the ASGI boundary — the body is never buffered

```env
MAX_REQUEST_BODY_BYTES=1048576  # 1 MiB default
```

### Research Goal Length (Application-level)

`POST /api/v1/runs` validates the `query` field length at two layers:

1. **Pydantic schema**: `max_length=2000` (static contract from Phase 5)
2. **Application logic**: Compared against `MAX_RESEARCH_GOAL_LENGTH` (default: 4000)

If `MAX_RESEARCH_GOAL_LENGTH` < Pydantic `max_length`, Pydantic enforces the tighter bound first. If longer, the application check provides the additional boundary.

```env
MAX_RESEARCH_GOAL_LENGTH=4000
```

---

## 7. Security Headers

The following headers are set on **every HTTP response** by `SecurityHeadersMiddleware`:

| Header | Value | Purpose |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `X-Frame-Options` | `DENY` | Prevents clickjacking via iframes |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Controls referrer leakage |
| `X-XSS-Protection` | `0` | Disables legacy XSS filter (modern browsers) |
| `Content-Security-Policy` | (see below) | Restricts resource loading |

### Content-Security-Policy

```
default-src 'self';
script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;
style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' data: https:;
connect-src 'self';
frame-ancestors 'none';
object-src 'none';
base-uri 'self';
```

`unsafe-inline` on `script-src` and `style-src` is required for FastAPI's embedded Swagger UI and ReDoc pages. Removing it would break `/docs` and `/redoc`. For hardened production APIs without interactive docs, these relaxations can be removed.

---

## 8. Error Behavior

All authentication, rate-limit, validation, and server errors return structured JSON responses:

```json
{
  "error_code": "UNAUTHORIZED",
  "message": "Authentication required. Provide a valid API key in the Authorization: Bearer header.",
  "details": null
}
```

### Guarantees

- **No stack traces** are returned to clients on any error path.
- **No secrets** (API keys, internal config values) appear in error response bodies.
- **No internal infrastructure details** (database names, service URLs) are exposed.
- HTTP status codes are consistent: 401 (auth), 422 (validation), 429 (rate limit), 413 (size), 500 (unexpected).
- The `WWW-Authenticate: Bearer` header is included on 401 responses per RFC 7235.

---

## 9. Configuration Reference

| Variable | Type | Default | Description |
|---|---|---|---|
| `API_AUTH_ENABLED` | bool | `false` | Enable API-key authentication |
| `API_KEY` | str | `""` | Shared API key (never commit real value) |
| `CORS_ALLOWED_ORIGINS` | str | `http://localhost:3000,...` | Comma-delimited allowed origins |
| `RATE_LIMIT_ENABLED` | bool | `false` | Enable sliding-window rate limiting |
| `RATE_LIMIT_REQUESTS` | int | `60` | Max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | int | `60` | Window size in seconds |
| `MAX_RESEARCH_GOAL_LENGTH` | int | `4000` | Max research query character length |
| `MAX_REQUEST_BODY_BYTES` | int | `1048576` | Max request body size in bytes |

---

## 10. Local Development Setup

### Unauthenticated (default, for development and testing)

```env
API_AUTH_ENABLED=false
RATE_LIMIT_ENABLED=false
```

The full test suite (`pytest backend/tests`) runs without any credentials configured.

### Authenticated (to simulate production)

```env
API_AUTH_ENABLED=true
API_KEY=your_strong_random_key_here
CORS_ALLOWED_ORIGINS=http://localhost:3000
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
```

Send requests with:
```
Authorization: Bearer your_strong_random_key_here
```

Generate a secure key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 11. Limitations

1. **Rate limiting is process-local** — See Section 5 for the distributed deployment warning and mitigation via `RateLimiterProtocol`.

2. **API key is a shared secret** — A single key is shared across all authorized clients. For per-client key rotation, replace with a key registry backed by a database; the `verify_api_key` dependency is designed to be extensible without route changes.

3. **Content-Length check only** — `RequestSizeLimitMiddleware` relies on the declared `Content-Length` header. Chunked transfer-encoded requests without a Content-Length header are not blocked at the ASGI layer. Reverse proxy enforcement (Nginx `client_max_body_size`, Cloud Run request size limits) is recommended as a complementary layer.

4. **No JWT/OAuth** — Authentication is deliberately simple (shared Bearer token) appropriate for the hackathon scope. For multi-tenant production deployments, replace with JWT validation or OAuth 2.0.

5. **No WAF** — This implementation does not include Web Application Firewall functionality. Rate limiting is a simple per-IP counter, not a behavioral anomaly detector.

---

## 12. Files Created / Modified

| File | Status | Description |
|---|---|---|
| `backend/app/config/settings.py` | Modified | Phase 6.5 security configuration fields |
| `backend/app/common/errors.py` | Modified | `APIAuthenticationError`, `RateLimitExceededError`, `RequestPayloadTooLargeError` |
| `backend/app/security/auth.py` | **New** | API-key authentication dependency |
| `backend/app/security/rate_limiter.py` | **New** | Rate limiter protocol + in-memory implementation |
| `backend/app/security/headers.py` | **New** | Security headers ASGI middleware |
| `backend/app/security/request_size.py` | **New** | Request-size ASGI middleware |
| `backend/app/security/__init__.py` | Modified | Updated exports |
| `backend/app/api/app.py` | Modified | Middleware stack, CORS hardening, exception handlers |
| `backend/app/api/routes.py` | Modified | Auth + rate-limit dependencies on protected routes |
| `.env.example` | Modified | Phase 6.5 configuration documentation |
| `backend/tests/unit/test_security_auth.py` | **New** | Auth unit + integration tests |
| `backend/tests/unit/test_rate_limiter.py` | **New** | Rate limiter unit + integration tests |
| `backend/tests/unit/test_security_headers_and_size.py` | **New** | Headers + size middleware tests |
| `backend/tests/integration/test_api_security_e2e.py` | **New** | Full security e2e test suite (15 scenarios) |
| `docs/phase6_5_implementation.md` | **New** | This document |

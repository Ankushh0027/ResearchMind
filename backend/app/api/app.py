"""FastAPI application factory and lifespan configuration."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.routes import set_global_service
from app.api.schemas import ErrorResponse
from app.api.service import ResearchService
from app.config.settings import get_settings
from app.observability.middleware import TraceContextMiddleware
from app.security.headers import SecurityHeadersMiddleware
from app.security.request_size import RequestSizeLimitMiddleware

logger = logging.getLogger(__name__)


def _build_cors_origins(settings_origins: tuple[str, ...]) -> list[str]:
    """Validate and return the configured CORS origins list.

    Wildcard '*' is disallowed here because the CORSMiddleware is configured
    with ``allow_credentials=True``; browsers refuse CORS with wildcard +
    credentials.  If the configured list contains a wildcard, it is silently
    filtered out and a warning is emitted.

    Args:
        settings_origins: Tuple of origin strings from ``AppSettings``.

    Returns:
        A list of safe, explicit origin strings.
    """
    origins: list[str] = []
    for origin in settings_origins:
        if origin.strip() == "*":
            logger.warning(
                "CORS wildcard '*' is not allowed when credentials are enabled. "
                "Dropping wildcard from allowed origins. "
                "Set CORS_ALLOWED_ORIGINS to explicit origin URLs."
            )
            continue
        origins.append(origin)
    if not origins:
        # Fall back to localhost only rather than allowing all origins
        logger.warning(
            "No valid CORS origins configured. Falling back to localhost:3000."
        )
        origins = ["http://localhost:3000"]
    return origins


def create_app(service: ResearchService | None = None) -> FastAPI:
    """Construct and configure the ResearchMind FastAPI application instance with clean lifespan."""
    settings = get_settings()
    active_service = service or ResearchService()
    set_global_service(active_service)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await active_service.start()
        yield
        await active_service.stop()

    app = FastAPI(
        title="ResearchMind API",
        description="Autonomous Asynchronous Research Agent Gateway",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )
    app.state.research_service = active_service

    # ------------------------------------------------------------------
    # Middleware stack (outermost added last — Starlette applies LIFO)
    # ------------------------------------------------------------------

    # 1. Request-size guard — cheapest, runs before body parsing
    app.add_middleware(RequestSizeLimitMiddleware)

    # 2. Security headers — applied to every response
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. CORS — use explicit origins, no wildcard when credentials enabled
    cors_origins = _build_cors_origins(settings.cors_allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "traceparent",
            "tracestate",
        ],
    )

    # 4. Distributed Trace Context & Correlation — outermost tracing boundary
    app.add_middleware(TraceContextMiddleware)

    # ------------------------------------------------------------------
    # Structured exception handlers — no stack traces, no secret leaks
    # ------------------------------------------------------------------

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request,  # noqa: ARG001 — required by Starlette handler signature
        exc: HTTPException,
    ) -> JSONResponse:
        """Return a structured ErrorResponse for all HTTPExceptions."""
        # exc.detail may already be a dict (from our security dependencies)
        if isinstance(exc.detail, dict):
            detail_dict = exc.detail
            error_code = str(detail_dict.get("error_code", "HTTP_ERROR"))
            message = str(detail_dict.get("message", str(exc.detail)))
            remaining = {
                k: v
                for k, v in detail_dict.items()
                if k not in ("error_code", "message")
            }
            details = remaining if remaining else None
        else:
            error_code = f"HTTP_{exc.status_code}"
            message = str(exc.detail)
            details = None

        body = ErrorResponse(
            error_code=error_code,
            message=message,
            details=details,
        )
        headers = dict(exc.headers) if exc.headers else {}
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request,  # noqa: ARG001 — required by Starlette handler signature
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Return structured 422 for request validation failures."""
        body = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        )
        return JSONResponse(
            status_code=422,
            content=body.model_dump(),
        )

    @app.exception_handler(Exception)
    async def _generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Return a safe 500 without leaking stack traces or internal details."""
        logger.exception(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        body = ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred. Please try again later.",
        )
        return JSONResponse(
            status_code=500,
            content=body.model_dump(),
        )

    # Attach router endpoints (high-priority REST & SSE routes)
    app.include_router(api_router)

    # Attach static web workspace if enabled and directory exists
    if settings.serve_frontend:
        frontend_dir = Path(__file__).resolve().parents[3] / "frontend"
        if not frontend_dir.exists():
            frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
        if not frontend_dir.exists():
            frontend_dir = Path("frontend").resolve()
        if frontend_dir.exists() and (frontend_dir / "index.html").exists():
            app.mount(
                "/",
                StaticFiles(directory=str(frontend_dir), html=True),
                name="frontend",
            )

    return app


__all__ = ["create_app"]

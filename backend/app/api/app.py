"""FastAPI application factory and middleware configuration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.routes import set_global_service
from app.api.service import ResearchService


def create_app(service: ResearchService | None = None) -> FastAPI:
    """Construct and configure the ResearchMind FastAPI application instance."""
    app = FastAPI(
        title="ResearchMind API",
        description="Autonomous Asynchronous Research Agent Gateway",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Configure CORS for frontend and API consumers
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Configure service backend
    if service is not None:
        set_global_service(service)

    # Attach router endpoints
    app.include_router(api_router)

    return app


__all__ = ["create_app"]

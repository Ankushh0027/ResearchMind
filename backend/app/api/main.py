"""Production entrypoint and CLI runner for ResearchMind FastAPI service."""

import uvicorn

from app.config import get_settings


def main() -> None:
    """Run the FastAPI application via uvicorn with configured environment settings."""
    settings = get_settings()
    uvicorn.run(
        "app.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()

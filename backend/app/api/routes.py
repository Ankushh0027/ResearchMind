"""FastAPI route handlers for REST endpoints and Server-Sent Events (SSE).

Phase 6.5 changes:
- ``/healthz`` remains publicly accessible (no auth, no rate limit).
- All ``/api/v1/*`` endpoints require ``verify_api_key`` when
  ``API_AUTH_ENABLED=true``.
- ``POST /api/v1/runs`` additionally enforces ``rate_limit_submissions``
  when ``RATE_LIMIT_ENABLED=true``.
- Research goal length is validated against ``MAX_RESEARCH_GOAL_LENGTH``
  before dispatching to the service layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    CancelRunResponse,
    CreateRunRequest,
    ErrorResponse,
    HealthResponse,
    RunDetailResponse,
    RunSummaryResponse,
)
from app.api.service import ResearchService
from app.config.settings import AppSettings, get_settings
from app.security.auth import verify_api_key
from app.security.rate_limiter import rate_limit_submissions

router = APIRouter()


def get_research_service() -> ResearchService:
    """Dependency resolver returning the active ResearchService singleton."""
    global _GLOBAL_SERVICE
    if _GLOBAL_SERVICE is None:
        _GLOBAL_SERVICE = ResearchService()
    return _GLOBAL_SERVICE


_GLOBAL_SERVICE: ResearchService | None = None


def set_global_service(service: ResearchService | None) -> None:
    """Explicitly configure or override the global ResearchService instance."""
    global _GLOBAL_SERVICE
    _GLOBAL_SERVICE = service


# ---------------------------------------------------------------------------
# Public endpoints (no authentication required)
# ---------------------------------------------------------------------------


@router.get(
    "/healthz",
    response_model=HealthResponse,
    tags=["System"],
    summary="System health and readiness check",
)
async def health_check() -> HealthResponse:
    """Return service liveness and readiness status.

    This endpoint is intentionally public and requires no authentication so
    that load balancers, monitoring systems, and CI readiness probes can
    reach it without credentials.
    """
    return HealthResponse()


# ---------------------------------------------------------------------------
# Protected endpoints — require API-key authentication when enabled
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/runs",
    response_model=RunSummaryResponse,
    status_code=201,
    tags=["Research"],
    summary="Submit a new research inquiry run",
    dependencies=[
        Depends(verify_api_key),
        Depends(rate_limit_submissions),
    ],
)
async def create_research_run(
    body: CreateRunRequest,
    service: ResearchService = Depends(get_research_service),
    settings: AppSettings = Depends(get_settings),
) -> RunSummaryResponse:
    """Submit a research inquiry to initiate multi-agent autonomous investigation.

    Protected by API-key authentication (when ``API_AUTH_ENABLED=true``) and
    sliding-window rate limiting (when ``RATE_LIMIT_ENABLED=true``).

    The research goal query is additionally bounded by
    ``MAX_RESEARCH_GOAL_LENGTH`` as a defence-in-depth input validation layer
    on top of Pydantic's existing ``max_length=2000`` constraint.
    """
    # Defence-in-depth: validate against the configurable max length in
    # addition to the Pydantic schema constraint.
    if len(body.query) > settings.max_research_goal_length:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": (
                    f"Research goal exceeds the maximum allowed length of "
                    f"{settings.max_research_goal_length} characters."
                ),
                "details": {
                    "field": "query",
                    "max_length": settings.max_research_goal_length,
                    "provided_length": len(body.query),
                },
            },
        )

    try:
        return await service.create_and_start_run(body)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "Failed to initiate research run.",
            },
        ) from e


@router.get(
    "/api/v1/runs/{run_id}",
    response_model=RunDetailResponse,
    tags=["Research"],
    summary="Get research run progress, metrics, and compiled ResearchDossier",
    dependencies=[Depends(verify_api_key)],
)
async def get_research_run(
    run_id: str,
    service: ResearchService = Depends(get_research_service),
) -> RunDetailResponse:
    """Fetch real-time status, subtask metrics, token usage, and final deliverable."""
    detail = await service.get_run(run_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "message": f"Research run '{run_id}' not found",
            },
        )
    return detail


@router.post(
    "/api/v1/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
    tags=["Research"],
    summary="Cancel an active research run",
    dependencies=[Depends(verify_api_key)],
)
async def cancel_research_run(
    run_id: str,
    service: ResearchService = Depends(get_research_service),
) -> CancelRunResponse:
    """Signal cooperative cancellation to halt active subtasks and mark the run CANCELLED."""
    try:
        return await service.cancel_run(run_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "message": f"Research run '{run_id}' not found",
            },
        ) from None
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "Cancellation failed.",
            },
        ) from e


@router.get(
    "/api/v1/runs/{run_id}/events",
    tags=["Research"],
    summary="Stream live execution events via Server-Sent Events (SSE)",
    dependencies=[Depends(verify_api_key)],
)
async def stream_run_events(
    run_id: str,
    service: ResearchService = Depends(get_research_service),
) -> StreamingResponse:
    """Subscribe to real-time Server-Sent Events (SSE) detailing task transitions and milestones."""
    detail = await service.get_run(run_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "message": f"Research run '{run_id}' not found",
            },
        )

    async def _sse_generator() -> AsyncIterator[str]:
        async for event_dict in service.stream_events(run_id):
            event_name = event_dict.get("event", "message")
            event_data = event_dict.get("data", "")
            yield f"event: {event_name}\ndata: {event_data}\n\n"

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "CancelRunResponse",
    "ErrorResponse",
    "cancel_research_run",
    "create_research_run",
    "get_research_run",
    "get_research_service",
    "health_check",
    "router",
    "set_global_service",
    "stream_run_events",
]

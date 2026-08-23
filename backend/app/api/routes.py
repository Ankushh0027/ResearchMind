"""FastAPI route handlers for REST endpoints and Server-Sent Events (SSE)."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    CancelRunResponse,
    CreateRunRequest,
    HealthResponse,
    RunDetailResponse,
    RunSummaryResponse,
)
from app.api.service import ResearchService

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


@router.get(
    "/healthz",
    response_model=HealthResponse,
    tags=["System"],
    summary="System health and readiness check",
)
async def health_check() -> HealthResponse:
    """Return service liveness and readiness status."""
    return HealthResponse()


@router.post(
    "/api/v1/runs",
    response_model=RunSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Research"],
    summary="Submit a new research inquiry run",
)
async def create_research_run(
    request: CreateRunRequest,
    service: ResearchService = Depends(get_research_service),
) -> RunSummaryResponse:
    """Submit a research inquiry to initiate multi-agent autonomous investigation."""
    try:
        return await service.create_and_start_run(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate research run: {e}",
        ) from e


@router.get(
    "/api/v1/runs/{run_id}",
    response_model=RunDetailResponse,
    tags=["Research"],
    summary="Get research run progress, metrics, and compiled ResearchDossier",
)
async def get_research_run(
    run_id: str,
    service: ResearchService = Depends(get_research_service),
) -> RunDetailResponse:
    """Fetch real-time status, subtask metrics, token usage, and final deliverable."""
    detail = await service.get_run(run_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        )
    return detail


@router.post(
    "/api/v1/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
    tags=["Research"],
    summary="Cancel an active research run",
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
        ) from None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cancellation failed: {e}",
        ) from e


@router.get(
    "/api/v1/runs/{run_id}/events",
    tags=["Research"],
    summary="Stream live execution events via Server-Sent Events (SSE)",
)
async def stream_run_events(
    run_id: str,
    service: ResearchService = Depends(get_research_service),
) -> StreamingResponse:
    """Subscribe to real-time Server-Sent Events (SSE) detailing task transitions and milestones."""
    detail = await service.get_run(run_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' not found",
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
    "cancel_research_run",
    "create_research_run",
    "get_research_run",
    "get_research_service",
    "health_check",
    "router",
    "set_global_service",
    "stream_run_events",
]

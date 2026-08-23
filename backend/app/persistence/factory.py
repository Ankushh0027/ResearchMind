"""Factory constructors for ResearchMind persistence layers."""

from app.config.settings import AppSettings, get_settings
from app.orchestration.protocols import CheckpointRepositoryProtocol
from app.persistence.firestore import (
    FirestoreCheckpointRepository,
    FirestoreEventRepository,
    FirestoreRunRepository,
)
from app.persistence.in_memory import (
    InMemoryCheckpointRepository,
    InMemoryEventRepository,
    InMemoryRunRepository,
)
from app.persistence.protocols import (
    EventRepositoryProtocol,
    RunRepositoryProtocol,
)


def create_run_repository(
    settings: AppSettings | None = None,
) -> RunRepositoryProtocol:
    """Instantiate configured RunRepository (InMemory or Firestore)."""
    cfg = settings or get_settings()
    if cfg.persistence_backend == "firestore":
        return FirestoreRunRepository(
            project_id=cfg.gcp_project_id,
            database=cfg.firestore_database,
            collection_name=cfg.firestore_runs_collection,
        )
    return InMemoryRunRepository()


def create_checkpoint_repository(
    settings: AppSettings | None = None,
) -> CheckpointRepositoryProtocol:
    """Instantiate configured CheckpointRepository (InMemory or Firestore)."""
    cfg = settings or get_settings()
    if cfg.persistence_backend == "firestore":
        return FirestoreCheckpointRepository(
            project_id=cfg.gcp_project_id,
            database=cfg.firestore_database,
        )
    return InMemoryCheckpointRepository()


def create_event_repository(
    settings: AppSettings | None = None,
) -> EventRepositoryProtocol:
    """Instantiate configured EventRepository (InMemory or Firestore)."""
    cfg = settings or get_settings()
    if cfg.persistence_backend == "firestore":
        return FirestoreEventRepository(
            project_id=cfg.gcp_project_id,
            database=cfg.firestore_database,
        )
    return InMemoryEventRepository()


__all__ = [
    "create_checkpoint_repository",
    "create_event_repository",
    "create_run_repository",
]

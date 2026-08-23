"""Persistence package exposing domain record models, protocols, and database adapters."""

from app.persistence.factory import (
    create_checkpoint_repository,
    create_event_repository,
    create_run_repository,
)
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
    CheckpointRepositoryProtocol,
    CheckpointSnapshot,
    EventRepositoryProtocol,
    RunContext,
    RunRecord,
    RunRepositoryProtocol,
)

__all__ = [
    "CheckpointRepositoryProtocol",
    "CheckpointSnapshot",
    "EventRepositoryProtocol",
    "FirestoreCheckpointRepository",
    "FirestoreEventRepository",
    "FirestoreRunRepository",
    "InMemoryCheckpointRepository",
    "InMemoryEventRepository",
    "InMemoryRunRepository",
    "RunContext",
    "RunRecord",
    "RunRepositoryProtocol",
    "create_checkpoint_repository",
    "create_event_repository",
    "create_run_repository",
]

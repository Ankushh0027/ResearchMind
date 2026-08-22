"""Checkpoint snapshot models and cryptographic state verification."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import RunStage
from app.common.errors import CheckpointCorruptedError
from app.state.models import RunState


def _utc_now() -> datetime:
    return datetime.now(UTC)


def compute_state_hash(payload: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of a JSON-serializable state payload."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class CheckpointSnapshot(BaseModel):
    """Immutable persistent state checkpoint with cryptographic tamper verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(
        ..., min_length=1, description="Unique snapshot identifier"
    )
    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    stage: RunStage = Field(..., description="Lifecycle stage at time of checkpoint")
    checkpoint_version: int = Field(
        ..., ge=1, description="Monotonically increasing checkpoint sequence number"
    )
    state_hash: str = Field(..., description="SHA-256 hash digest of the state payload")
    state_payload: dict[str, Any] = Field(
        ..., description="Full serialized state payload"
    )
    created_at: datetime = Field(default_factory=_utc_now)

    def verify_integrity(self) -> bool:
        """Verify that the computed hash of the payload matches the recorded state_hash."""
        expected_hash = compute_state_hash(self.state_payload)
        return self.state_hash == expected_hash

    def assert_valid(self) -> None:
        """Raise CheckpointCorruptedError if state integrity verification fails."""
        expected_hash = compute_state_hash(self.state_payload)
        if self.state_hash != expected_hash:
            raise CheckpointCorruptedError(
                snapshot_id=self.snapshot_id,
                expected_hash=self.state_hash,
                computed_hash=expected_hash,
            )


def create_checkpoint(run_state: RunState) -> CheckpointSnapshot:
    """Create an immutable CheckpointSnapshot from an active RunState."""
    new_version = run_state.checkpoint_counter + 1
    state_dict = run_state.model_dump(mode="json")
    state_hash = compute_state_hash(state_dict)

    snapshot_id = f"chk_{run_state.run_id}_{new_version:04d}"

    return CheckpointSnapshot(
        snapshot_id=snapshot_id,
        run_id=run_state.run_id,
        stage=run_state.current_stage,
        checkpoint_version=new_version,
        state_hash=state_hash,
        state_payload=state_dict,
        created_at=_utc_now(),
    )

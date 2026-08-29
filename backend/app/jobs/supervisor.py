import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import RunStage
from app.jobs.lease import (
    LeaseManagerProtocol,
    generate_worker_id,
)
from app.jobs.protocols import JobEnvelope, JobPublisherProtocol, JobStatus
from app.observability.factory import get_metrics
from app.orchestration.protocols import CheckpointRepositoryProtocol
from app.persistence.protocols import RunRepositoryProtocol

logger = logging.getLogger("researchmind.worker.supervisor")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecoveryStatus(StrEnum):
    """Outcome status of an automated recovery cycle."""

    RECOVERED = "RECOVERED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class RecoveryReport(BaseModel):
    """Detailed audit record produced after examining or recovering a stale run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Target research run ID")
    recovery_attempt: int = Field(
        default=0, ge=0, description="Attempt number for this recovery"
    )
    status: RecoveryStatus = Field(..., description="Resulting recovery outcome status")
    checkpoint_id: str | None = Field(
        default=None, description="Snapshot ID of restored checkpoint"
    )
    checkpoint_version: int | None = Field(
        default=None, description="Version number of restored checkpoint"
    )
    republished: bool = Field(
        default=False, description="Whether job envelope was republished"
    )
    error: str | None = Field(
        default=None, description="Error message or failure reason if applicable"
    )
    recovered_at: datetime = Field(
        default_factory=_utc_now, description="Timestamp recovery was processed"
    )


ACTIVE_RUN_STAGES = (
    RunStage.PLANNING,
    RunStage.RESEARCHING,
    RunStage.ANALYZING,
    RunStage.VERIFYING,
    RunStage.EVALUATING,
    RunStage.REPORTING,
)


class LeaseSupervisor:
    """Monitors worker leases, reclaims stale/crashed runs, and restores execution context."""

    def __init__(
        self,
        run_repo: RunRepositoryProtocol,
        checkpoint_repo: CheckpointRepositoryProtocol,
        publisher: JobPublisherProtocol,
        lease_manager: LeaseManagerProtocol,
        max_recovery_attempts: int = 3,
        supervisor_id: str | None = None,
    ) -> None:
        self.run_repo = run_repo
        self.checkpoint_repo = checkpoint_repo
        self.publisher = publisher
        self.lease_manager = lease_manager
        self.max_recovery_attempts = max(1, max_recovery_attempts)
        self.supervisor_id = supervisor_id or generate_worker_id(prefix="supervisor")
        self._lock = asyncio.Lock()

    async def reap_stale_runs(self, limit: int = 50) -> list[RecoveryReport]:
        """Scan active research runs, identify stale leases, and execute recovery."""
        reports: list[RecoveryReport] = []
        now = _utc_now()

        try:
            runs = await self.run_repo.list_runs(limit=limit)
        except Exception as e:
            logger.error("Failed to query run repository for stale leases: %s", e)
            return reports

        for run in runs:
            if run.status not in ACTIVE_RUN_STAGES:
                continue

            # A run is stale if its lease has expired
            is_stale = False
            if run.lease_expires_at is not None and run.lease_expires_at <= now:
                is_stale = True
            elif run.lease_expires_at is None and run.status in ACTIVE_RUN_STAGES:
                # Orphaned active run with no lease
                is_stale = True

            if is_stale:
                logger.info(
                    "Detected stale lease for run '%s' (stage: %s, lease_id: %s). Initiating recovery.",
                    run.run_id,
                    run.status,
                    run.lease_id,
                )
                report = await self.recover_run(run.run_id)
                reports.append(report)

        return reports

    async def recover_run(self, run_id: str) -> RecoveryReport:
        """Atomically claim and recover a single stale research run."""
        metrics = get_metrics()

        # Step 1: Atomic Recovery Claim
        # Attempt to acquire lease under supervisor identity to prevent race conditions
        claim_lease = await self.lease_manager.acquire_lease(
            run_id=run_id,
            worker_id=f"supervisor-{self.supervisor_id}",
            duration_seconds=60.0,
        )

        if claim_lease is None:
            # Another supervisor or worker holds an unexpired lease
            logger.debug(
                "Skipping recovery for run '%s': could not acquire supervisor claim lease.",
                run_id,
            )
            return RecoveryReport(
                run_id=run_id,
                status=RecoveryStatus.SKIPPED,
                error="Could not acquire supervisor recovery claim lease",
            )

        try:
            record = await self.run_repo.get_run(run_id)
            if record is None:
                return RecoveryReport(
                    run_id=run_id,
                    status=RecoveryStatus.SKIPPED,
                    error="RunRecord not found",
                )

            if record.status not in ACTIVE_RUN_STAGES:
                await self.lease_manager.release_lease(
                    run_id=run_id,
                    worker_id=f"supervisor-{self.supervisor_id}",
                    lease_id=claim_lease.lease_id,
                )
                return RecoveryReport(
                    run_id=run_id,
                    recovery_attempt=record.recovery_attempt,
                    status=RecoveryStatus.SKIPPED,
                    error=f"Run is not in an active stage (currently {record.status})",
                )

            # Step 2: Cancellation Check
            if record.is_cancelled:
                logger.info(
                    "Run '%s' was cancelled. Transitioning to CANCELLED without republishing.",
                    run_id,
                )
                updated = record.with_updates(
                    status=RunStage.CANCELLED,
                    clear_lease=True,
                )
                await self.run_repo.update_run(updated)
                return RecoveryReport(
                    run_id=run_id,
                    recovery_attempt=record.recovery_attempt,
                    status=RecoveryStatus.CANCELLED,
                    error="Run was cancelled by user",
                )

            # Step 3: Check Maximum Recovery Attempts
            next_attempt = record.recovery_attempt + 1
            if next_attempt > self.max_recovery_attempts:
                logger.warning(
                    "Run '%s' exceeded maximum recovery attempts (%d/%d). Marking permanently FAILED.",
                    run_id,
                    record.recovery_attempt,
                    self.max_recovery_attempts,
                )
                metrics.increment_counter(
                    "worker.recovery.exhausted",
                    attributes={
                        "run_id": run_id,
                        "attempts": str(record.recovery_attempt),
                    },
                )
                updated = record.with_updates(
                    status=RunStage.FAILED,
                    error=f"Maximum failure recovery attempts ({self.max_recovery_attempts}) exhausted.",
                    clear_lease=True,
                )
                await self.run_repo.update_run(updated)
                return RecoveryReport(
                    run_id=run_id,
                    recovery_attempt=record.recovery_attempt,
                    status=RecoveryStatus.EXHAUSTED,
                    error=f"Maximum recovery attempts ({self.max_recovery_attempts}) exhausted",
                )

            # Step 4: Checkpoint Verification & State Restoration
            metrics.increment_counter(
                "worker.recovery.started",
                attributes={"run_id": run_id, "attempt": str(next_attempt)},
            )

            checkpoint_id: str | None = None
            checkpoint_version: int | None = None
            target_stage = RunStage.QUEUED

            try:
                latest_ckpt = await self.checkpoint_repo.load_latest_checkpoint(run_id)
                if latest_ckpt is not None:
                    latest_ckpt.assert_valid()
                    checkpoint_id = latest_ckpt.snapshot_id
                    checkpoint_version = latest_ckpt.checkpoint_version
                    target_stage = latest_ckpt.stage
                    logger.info(
                        "Restored valid checkpoint '%s' (v%d, stage: %s) for run '%s'.",
                        checkpoint_id,
                        checkpoint_version,
                        target_stage,
                        run_id,
                    )
            except Exception as ckpt_err:
                logger.warning(
                    "Checkpoint load or verification failed for run '%s': %s. Re-queueing from beginning.",
                    run_id,
                    ckpt_err,
                )

            # Step 5: Update Run Record & Clear Lease for Next Worker
            updated_record = record.with_updates(
                status=target_stage,
                recovery_attempt=next_attempt,
                last_checkpoint_id=checkpoint_id,
                clear_lease=True,
            )
            await self.run_repo.update_run(updated_record)

            # Step 6: Republish Job Envelope
            envelope = JobEnvelope(
                job_id=f"job_rec_{run_id}_att{next_attempt}_{uuid.uuid4().hex[:6]}",
                run_id=run_id,
                goal_query=record.goal.query,
                domain_tags=tuple(record.goal.domain_tags),
                constraints=record.goal.constraints,
                max_subtasks=record.goal.max_subtasks,
                attempt=next_attempt,
                max_attempts=self.max_recovery_attempts,
                status=JobStatus.QUEUED,
                metadata={
                    "recovery_attempt": next_attempt,
                    "recovered_from_checkpoint": checkpoint_id,
                    "restored_checkpoint_version": checkpoint_version,
                },
            )

            await self.publisher.publish(envelope)

            metrics.increment_counter(
                "worker.recovery.completed",
                attributes={"run_id": run_id, "attempt": str(next_attempt)},
            )
            logger.info(
                "Successfully recovered and republished run '%s' (attempt: %d/%d).",
                run_id,
                next_attempt,
                self.max_recovery_attempts,
            )

            return RecoveryReport(
                run_id=run_id,
                recovery_attempt=next_attempt,
                status=RecoveryStatus.RECOVERED,
                checkpoint_id=checkpoint_id,
                checkpoint_version=checkpoint_version,
                republished=True,
            )

        except Exception as e:
            logger.error("Unexpected error during recovery of run '%s': %s", run_id, e)
            metrics.increment_counter(
                "worker.recovery.failed", attributes={"run_id": run_id}
            )
            # Ensure lease is released on unexpected failure
            with contextlib.suppress(Exception):
                await self.lease_manager.release_lease(
                    run_id=run_id,
                    worker_id=f"supervisor-{self.supervisor_id}",
                    lease_id=claim_lease.lease_id,
                )

            return RecoveryReport(
                run_id=run_id,
                status=RecoveryStatus.FAILED,
                error=str(e),
            )


__all__ = [
    "ACTIVE_RUN_STAGES",
    "LeaseSupervisor",
    "RecoveryReport",
    "RecoveryStatus",
]

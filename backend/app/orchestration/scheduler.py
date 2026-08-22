"""Dependency-aware DAG scheduler and task lifecycle coordinator."""

import contextlib
from datetime import UTC, datetime

from app.common.enums import TaskStatus
from app.common.errors import DeadlockDetectedError, SchedulerError
from app.state.models import ResearchPlan, SubtaskNode, TaskStateRecord
from app.state.transitions import validate_task_transition
from app.tasks.dag import DAGValidator, ValidatedDAG


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DAGScheduler:
    """Dependency-aware DAG scheduler enforcing prerequisite satisfaction and deterministic selection."""

    def __init__(
        self,
        plan: ResearchPlan,
        validated_dag: ValidatedDAG | None = None,
        initial_tasks: dict[str, TaskStateRecord] | None = None,
    ) -> None:
        self._plan = plan
        if validated_dag is None:
            validator = DAGValidator()
            self._dag = validator.validate_plan(plan)
        else:
            self._dag = validated_dag

        self._task_records: dict[str, TaskStateRecord] = {}

        # Initialize or populate from recovered state
        for node_id, node in self._plan.nodes.items():
            if initial_tasks and node_id in initial_tasks:
                self._task_records[node_id] = initial_tasks[node_id]
            else:
                idempotency_key = (
                    f"idem_{self._plan.run_id}_{node_id}_v{self._plan.version}"
                )
                self._task_records[node_id] = TaskStateRecord(
                    subtask_id=node_id,
                    run_id=self._plan.run_id,
                    status=TaskStatus.PENDING,
                    attempt_count=0,
                    max_attempts=node.max_retries,
                    idempotency_key=idempotency_key,
                )

    @property
    def run_id(self) -> str:
        """Return the active research run ID."""
        return self._plan.run_id

    @property
    def plan_id(self) -> str:
        """Return the active plan ID."""
        return self._plan.plan_id

    @property
    def total_tasks_count(self) -> int:
        """Return the total number of subtask nodes in the plan."""
        return len(self._plan.nodes)

    def get_runnable_tasks(self) -> list[SubtaskNode]:
        """Return all tasks in PENDING state whose prerequisite dependencies are COMPLETED.

        Output list is deterministically sorted alphabetically by subtask_id.
        """
        runnable: list[SubtaskNode] = []

        for node_id in sorted(self._plan.nodes.keys()):
            record = self._task_records[node_id]
            if record.status != TaskStatus.PENDING:
                continue

            # Check prerequisites
            prerequisites = self._dag.node_dependencies.get(node_id, ())
            all_prereqs_completed = all(
                self._task_records[p_id].status == TaskStatus.COMPLETED
                for p_id in prerequisites
            )

            if all_prereqs_completed:
                runnable.append(self._plan.nodes[node_id])

        return runnable

    def mark_scheduled(self, subtask_id: str) -> TaskStateRecord:
        """Transition task from PENDING to SCHEDULED."""
        record = self._get_record(subtask_id)
        validate_task_transition(subtask_id, record.status, TaskStatus.SCHEDULED)

        updated = record.model_copy(update={"status": TaskStatus.SCHEDULED})
        self._task_records[subtask_id] = updated
        return updated

    def mark_started(
        self, subtask_id: str, worker_id: str, attempt: int
    ) -> TaskStateRecord:
        """Transition task from SCHEDULED to IN_PROGRESS."""
        record = self._get_record(subtask_id)
        validate_task_transition(subtask_id, record.status, TaskStatus.IN_PROGRESS)

        updated = record.model_copy(
            update={
                "status": TaskStatus.IN_PROGRESS,
                "worker_id": worker_id,
                "attempt_count": attempt,
                "started_at": _utc_now(),
                "error_message": None,
            }
        )
        self._task_records[subtask_id] = updated
        return updated

    def mark_completed(self, subtask_id: str) -> TaskStateRecord:
        """Transition task from IN_PROGRESS to COMPLETED."""
        record = self._get_record(subtask_id)
        validate_task_transition(subtask_id, record.status, TaskStatus.COMPLETED)

        updated = record.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "completed_at": _utc_now(),
                "error_message": None,
            }
        )
        self._task_records[subtask_id] = updated
        return updated

    def mark_failed(self, subtask_id: str, error_message: str) -> TaskStateRecord:
        """Transition task from IN_PROGRESS to FAILED."""
        record = self._get_record(subtask_id)
        validate_task_transition(subtask_id, record.status, TaskStatus.FAILED)

        updated = record.model_copy(
            update={
                "status": TaskStatus.FAILED,
                "completed_at": _utc_now(),
                "error_message": error_message,
            }
        )
        self._task_records[subtask_id] = updated
        return updated

    def mark_retry_scheduled(self, subtask_id: str) -> TaskStateRecord:
        """Transition task from FAILED to SCHEDULED for a retry attempt."""
        record = self._get_record(subtask_id)
        validate_task_transition(subtask_id, record.status, TaskStatus.SCHEDULED)

        updated = record.model_copy(
            update={
                "status": TaskStatus.SCHEDULED,
                "started_at": None,
                "completed_at": None,
            }
        )
        self._task_records[subtask_id] = updated
        return updated

    def mark_cancelled(
        self, subtask_id: str, reason: str = "Run cancelled"
    ) -> TaskStateRecord:
        """Transition task to CANCELLED."""
        record = self._get_record(subtask_id)
        if record.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return record

        with contextlib.suppress(Exception):
            validate_task_transition(subtask_id, record.status, TaskStatus.CANCELLED)

        updated = record.model_copy(
            update={
                "status": TaskStatus.CANCELLED,
                "completed_at": _utc_now(),
                "error_message": reason,
            }
        )
        self._task_records[subtask_id] = updated
        return updated

    def is_all_completed(self) -> bool:
        """Check if every task in the plan has reached COMPLETED status."""
        return all(
            record.status == TaskStatus.COMPLETED
            for record in self._task_records.values()
        )

    def is_terminal(self) -> bool:
        """Check if all tasks are in terminal states (COMPLETED, FAILED, CANCELLED, SKIPPED)."""
        terminal_statuses = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
        return all(r.status in terminal_statuses for r in self._task_records.values())

    def get_active_count(self) -> int:
        """Count tasks currently scheduled or executing."""
        active_statuses = {TaskStatus.SCHEDULED, TaskStatus.IN_PROGRESS}
        return sum(
            1 for r in self._task_records.values() if r.status in active_statuses
        )

    def check_and_raise_deadlock(self) -> None:
        """Evaluate if the graph is deadlocked (uncompleted tasks exist, 0 active, 0 runnable)."""
        if self.is_terminal():
            return

        runnable = self.get_runnable_tasks()
        active_count = self.get_active_count()

        if len(runnable) == 0 and active_count == 0:
            uncompleted = [
                nid
                for nid, rec in self._task_records.items()
                if rec.status
                not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.SKIPPED)
            ]
            if uncompleted:
                raise DeadlockDetectedError(
                    run_id=self.run_id, uncompleted_task_ids=sorted(uncompleted)
                )

    def get_task_state(self, subtask_id: str) -> TaskStateRecord:
        """Retrieve task state record by ID."""
        return self._get_record(subtask_id)

    def get_all_task_states(self) -> dict[str, TaskStateRecord]:
        """Return a copy of all task state records."""
        return dict(self._task_records)

    def _get_record(self, subtask_id: str) -> TaskStateRecord:
        if subtask_id not in self._task_records:
            raise SchedulerError(
                f"Task '{subtask_id}' is not part of plan '{self.plan_id}'"
            )
        return self._task_records[subtask_id]

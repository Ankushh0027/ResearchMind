"""Execution engine coordinating DAG traversal, worker dispatch, retries, and recovery."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import RunStage, TaskStatus, ToolPermission
from app.common.errors import (
    CheckpointRecoveryError,
    DeadlockDetectedError,
)
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.events import (
    DeadlockDetectedEvent,
    ExecutionEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskRetryScheduledEvent,
    TaskScheduledEvent,
    TaskStartedEvent,
)
from app.orchestration.protocols import (
    CheckpointRepositoryProtocol,
    EventSinkProtocol,
    ObservabilityHooksProtocol,
    WorkerProtocol,
)
from app.orchestration.retry import (
    RetryPolicy,
    SleeperType,
    default_async_sleeper,
)
from app.orchestration.runtime import (
    InMemoryCheckpointRepository,
    InMemoryEventSink,
    MetricsCollector,
)
from app.orchestration.scheduler import DAGScheduler
from app.orchestration.worker import MockWorker, WorkerRegistry
from app.security.permissions import SecurityPolicy
from app.state.models import ResearchPlan, RunState, SubtaskNode
from app.state.snapshot import CheckpointSnapshot, create_checkpoint
from app.tasks.dag import DAGValidator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionResult(BaseModel):
    """Aggregate result of an executed research plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(...)
    plan_id: str = Field(...)
    status: RunStage = Field(...)
    completed_task_ids: tuple[str, ...] = Field(default_factory=tuple)
    failed_task_ids: tuple[str, ...] = Field(default_factory=tuple)
    cancelled_task_ids: tuple[str, ...] = Field(default_factory=tuple)
    task_outputs: dict[str, Any] = Field(default_factory=dict)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    total_token_usage: TokenUsage = Field(default_factory=TokenUsage)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    events: tuple[ExecutionEvent, ...] = Field(default_factory=tuple)
    error: str | None = Field(default=None)

    @property
    def is_success(self) -> bool:
        """Return True if the run completed all tasks successfully."""
        return self.status == RunStage.COMPLETED


class DAGExecutor:
    """Framework-agnostic asynchronous execution engine for research task graphs."""

    def __init__(
        self,
        max_concurrency: int = 5,
        worker_registry: WorkerRegistry | WorkerProtocol | None = None,
        retry_policy: RetryPolicy | None = None,
        checkpoint_repo: CheckpointRepositoryProtocol | None = None,
        event_sink: EventSinkProtocol | None = None,
        observability_hook: ObservabilityHooksProtocol | None = None,
        sleeper: SleeperType = default_async_sleeper,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.worker_registry = worker_registry or WorkerRegistry(
            default_worker=MockWorker()
        )
        self.retry_policy = retry_policy or RetryPolicy()
        self.checkpoint_repo = checkpoint_repo or InMemoryCheckpointRepository()
        self.event_sink = event_sink or InMemoryEventSink()
        self.observability_hook = observability_hook or MetricsCollector()
        self.sleeper = sleeper

    async def execute_plan(
        self,
        plan: ResearchPlan,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Execute a research plan from beginning to end with dependency-aware concurrency."""
        validator = DAGValidator()
        validated_dag = validator.validate_plan(plan)

        scheduler = DAGScheduler(plan=plan, validated_dag=validated_dag)
        return await self._run_scheduler(plan, scheduler, cancellation_token)

    async def resume_from_checkpoint(
        self,
        snapshot: CheckpointSnapshot,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Resume an incomplete execution from a verified CheckpointSnapshot."""
        snapshot.assert_valid()

        try:
            run_state = RunState.model_validate(snapshot.state_payload)
        except Exception as e:
            raise CheckpointRecoveryError(
                run_id=snapshot.run_id, reason=f"State deserialization failed: {e}"
            ) from e

        if run_state.active_plan is None:
            raise CheckpointRecoveryError(
                run_id=snapshot.run_id,
                reason="Checkpoint contains no active research plan",
            )

        plan = run_state.active_plan
        validator = DAGValidator()
        validated_dag = validator.validate_plan(plan)

        scheduler = DAGScheduler(
            plan=plan,
            validated_dag=validated_dag,
            initial_tasks=dict(run_state.tasks),
        )

        return await self._run_scheduler(plan, scheduler, cancellation_token)

    async def _run_scheduler(
        self,
        plan: ResearchPlan,
        scheduler: DAGScheduler,
        cancellation_token: CancellationToken | None,
    ) -> ExecutionResult:
        start_time = time.monotonic()
        run_id = plan.run_id
        plan_id = plan.plan_id
        token = cancellation_token or CancellationToken()

        semaphore = asyncio.Semaphore(self.max_concurrency)
        running_tasks: dict[str, asyncio.Task[WorkerResponseEnvelope]] = {}
        task_outputs: dict[str, Any] = {}
        task_retries: dict[str, int] = {}
        total_token_usage = TokenUsage()
        completed_task_ids: list[str] = []
        failed_task_ids: list[str] = []
        cancelled_task_ids: list[str] = []
        terminal_error: str | None = None

        # Emit RunStartedEvent
        await self._emit_event(
            RunStartedEvent(
                run_id=run_id,
                plan_id=plan_id,
                total_tasks=scheduler.total_tasks_count,
            )
        )
        await self.observability_hook.on_run_started(run_id, plan_id)

        # Check existing completed tasks (from recovery)
        for tid, trec in scheduler.get_all_task_states().items():
            if trec.status == TaskStatus.COMPLETED:
                completed_task_ids.append(tid)

        try:
            while not scheduler.is_all_completed():
                # 1. Handle Cancellation
                if token.is_cancelled:
                    for tid in scheduler.get_all_task_states():
                        rec = scheduler.get_task_state(tid)
                        if rec.status not in (
                            TaskStatus.COMPLETED,
                            TaskStatus.CANCELLED,
                        ):
                            scheduler.mark_cancelled(
                                tid, reason=token.reason or "Run cancelled"
                            )
                            cancelled_task_ids.append(tid)
                            await self._emit_event(
                                TaskCancelledEvent(
                                    run_id=run_id,
                                    subtask_id=tid,
                                    reason=token.reason or "Run cancelled",
                                )
                            )

                    # Cancel any in-flight asyncio tasks
                    for running_t in running_tasks.values():
                        running_t.cancel()

                    break

                # 2. Deadlock Detection
                try:
                    scheduler.check_and_raise_deadlock()
                except DeadlockDetectedError as e:
                    terminal_error = str(e)
                    await self._emit_event(
                        DeadlockDetectedEvent(
                            run_id=run_id,
                            uncompleted_task_ids=tuple(e.uncompleted_task_ids),
                        )
                    )
                    break

                # 3. Schedule Runnable Tasks
                runnable_nodes = scheduler.get_runnable_tasks()
                for node in runnable_nodes:
                    if node.subtask_id in running_tasks:
                        continue

                    # Security Permission Enforcement
                    self._enforce_security_policy(node)

                    # Mark Scheduled
                    scheduler.mark_scheduled(node.subtask_id)
                    await self._emit_event(
                        TaskScheduledEvent(
                            run_id=run_id,
                            subtask_id=node.subtask_id,
                            task_type=node.task_type,
                            assigned_role=node.assigned_role,
                            attempt=1,
                        )
                    )

                    # Spawn task with concurrency limiter
                    task_future = asyncio.create_task(
                        self._execute_subtask_lifecycle(
                            plan=plan,
                            node=node,
                            scheduler=scheduler,
                            semaphore=semaphore,
                            token=token,
                            task_outputs=task_outputs,
                        )
                    )
                    running_tasks[node.subtask_id] = task_future

                if not running_tasks:
                    if scheduler.is_terminal():
                        break
                    # No tasks running and none runnable -> check deadlock or break
                    scheduler.check_and_raise_deadlock()
                    break

                # 4. Wait for any running task to complete
                done, _ = await asyncio.wait(
                    running_tasks.values(), return_when=asyncio.FIRST_COMPLETED
                )

                # Process completed task results
                for task_future in done:
                    # Find matching subtask_id
                    subtask_id = next(
                        (
                            sid
                            for sid, fut in running_tasks.items()
                            if fut == task_future
                        ),
                        None,
                    )
                    if subtask_id:
                        del running_tasks[subtask_id]

                    envelope = await task_future

                    if envelope.status == TaskStatus.COMPLETED:
                        completed_task_ids.append(envelope.subtask_id)
                        if envelope.response and envelope.response.output_data:
                            task_outputs[envelope.subtask_id] = (
                                envelope.response.output_data
                            )
                        if envelope.response:
                            total_token_usage = TokenUsage(
                                prompt_tokens=total_token_usage.prompt_tokens
                                + envelope.response.token_usage.prompt_tokens,
                                completion_tokens=total_token_usage.completion_tokens
                                + envelope.response.token_usage.completion_tokens,
                                total_tokens=total_token_usage.total_tokens
                                + envelope.response.token_usage.total_tokens,
                            )
                    elif envelope.status == TaskStatus.FAILED:
                        failed_task_ids.append(envelope.subtask_id)
                        if envelope.error:
                            terminal_error = envelope.error.message
                    elif envelope.status == TaskStatus.CANCELLED:
                        cancelled_task_ids.append(envelope.subtask_id)

                # Save Checkpoint Snapshot
                await self._save_progress_checkpoint(plan, scheduler)

        except Exception as e:
            terminal_error = f"Orchestrator error: {e}"

        duration = time.monotonic() - start_time

        # Determine final status
        if token.is_cancelled:
            final_stage = RunStage.CANCELLED
            await self._emit_event(
                RunCancelledEvent(
                    run_id=run_id,
                    reason=token.reason or "Run cancelled",
                    completed_tasks_count=len(completed_task_ids),
                )
            )
        elif scheduler.is_all_completed():
            final_stage = RunStage.COMPLETED
            await self._emit_event(
                RunCompletedEvent(
                    run_id=run_id,
                    plan_id=plan_id,
                    total_tasks_completed=len(completed_task_ids),
                    duration_seconds=duration,
                    total_token_usage=total_token_usage,
                )
            )
            await self.observability_hook.on_run_completed(
                run_id, duration, total_token_usage
            )
        else:
            final_stage = RunStage.FAILED
            await self._emit_event(
                RunFailedEvent(
                    run_id=run_id,
                    error_type="ExecutionFailure",
                    error_message=terminal_error or "One or more tasks failed",
                    failed_subtask_id=failed_task_ids[0] if failed_task_ids else None,
                )
            )

        recorded_events = (
            self.event_sink.get_events(run_id)
            if isinstance(self.event_sink, InMemoryEventSink)
            else []
        )

        return ExecutionResult(
            run_id=run_id,
            plan_id=plan_id,
            status=final_stage,
            completed_task_ids=tuple(sorted(set(completed_task_ids))),
            failed_task_ids=tuple(sorted(set(failed_task_ids))),
            cancelled_task_ids=tuple(sorted(set(cancelled_task_ids))),
            task_outputs=task_outputs,
            retry_counts=task_retries,
            total_token_usage=total_token_usage,
            duration_seconds=duration,
            events=tuple(recorded_events),
            error=terminal_error,
        )

    async def _execute_subtask_lifecycle(
        self,
        plan: ResearchPlan,
        node: SubtaskNode,
        scheduler: DAGScheduler,
        semaphore: asyncio.Semaphore,
        token: CancellationToken,
        task_outputs: dict[str, Any] | None = None,
    ) -> WorkerResponseEnvelope:
        """Execute a subtask with retry backoff, timeouts, and lifecycle event tracking."""
        subtask_id = node.subtask_id
        if isinstance(self.worker_registry, WorkerRegistry):
            worker: WorkerProtocol = self.worker_registry.get_worker(node.assigned_role)
        elif isinstance(self.worker_registry, WorkerProtocol):
            worker = self.worker_registry
        else:
            worker = getattr(
                self.worker_registry,
                "get_worker",
                lambda _r: self.worker_registry,
            )(node.assigned_role)

        attempt = 1
        max_attempts = node.max_retries

        async with semaphore:
            while attempt <= max_attempts:
                if token.is_cancelled:
                    scheduler.mark_cancelled(
                        subtask_id, reason=token.reason or "Cancelled"
                    )
                    return WorkerResponseEnvelope(
                        envelope_id=f"env_{uuid.uuid4().hex[:12]}",
                        dispatch_id=f"disp_{subtask_id}",
                        run_id=plan.run_id,
                        subtask_id=subtask_id,
                        status=TaskStatus.CANCELLED,
                        worker_id="coordinator",
                    )

                # Transition to IN_PROGRESS
                worker_id = getattr(
                    worker,
                    "worker_id",
                    getattr(worker, "router_id", f"{node.assigned_role.value}-worker"),
                )
                scheduler.mark_started(subtask_id, worker_id, attempt)
                await self._emit_event(
                    TaskStartedEvent(
                        run_id=plan.run_id,
                        subtask_id=subtask_id,
                        worker_id=worker_id,
                        attempt=attempt,
                    )
                )
                await self.observability_hook.on_task_started(
                    plan.run_id, subtask_id, attempt
                )

                # Merge node input_context with upstream outputs from completed dependencies
                merged_input_data = dict(node.input_context)
                if (
                    node.search_queries
                    and "queries" not in merged_input_data
                    and "search_queries" not in merged_input_data
                ):
                    merged_input_data["search_queries"] = list(node.search_queries)

                if task_outputs is not None:
                    ancestors: set[str] = set()
                    to_visit = list(
                        scheduler._dag.node_dependencies.get(subtask_id, ())
                    )
                    while to_visit:
                        curr = to_visit.pop()
                        if curr not in ancestors:
                            ancestors.add(curr)
                            to_visit.extend(
                                scheduler._dag.node_dependencies.get(curr, ())
                            )

                    for p_id in sorted(ancestors):
                        if p_id in task_outputs:
                            p_out = task_outputs[p_id]
                            if isinstance(p_out, dict):
                                for list_key in (
                                    "evidence_records",
                                    "claims",
                                    "findings",
                                    "key_findings",
                                    "citations",
                                    "contradictions",
                                ):
                                    if list_key in p_out and isinstance(
                                        p_out[list_key], list
                                    ):
                                        target_key = (
                                            "findings"
                                            if list_key == "key_findings"
                                            else list_key
                                        )
                                        if target_key not in merged_input_data:
                                            merged_input_data[target_key] = []
                                        elif not isinstance(
                                            merged_input_data[target_key], list
                                        ):
                                            merged_input_data[target_key] = [
                                                merged_input_data[target_key]
                                            ]
                                        for item in p_out[list_key]:
                                            if (
                                                item
                                                not in merged_input_data[target_key]
                                            ):
                                                merged_input_data[target_key].append(
                                                    item
                                                )
                                for obj_key in (
                                    "evaluation",
                                    "evaluation_report",
                                    "verification_result",
                                    "queries",
                                    "goal_query",
                                ):
                                    if (
                                        obj_key in p_out
                                        and obj_key not in merged_input_data
                                    ):
                                        target_key = (
                                            "evaluation"
                                            if obj_key == "evaluation_report"
                                            else obj_key
                                        )
                                        merged_input_data[target_key] = p_out[obj_key]

                idempotency_key = f"idem_{plan.run_id}_{subtask_id}_att{attempt}"
                request = AgentRequest(
                    request_id=f"req_{uuid.uuid4().hex[:12]}",
                    run_id=plan.run_id,
                    subtask_id=subtask_id,
                    agent_role=node.assigned_role,
                    task_type=node.task_type,
                    goal_context=plan.goal.query,
                    input_data=merged_input_data,
                    idempotency_key=idempotency_key,
                    attempt_number=attempt,
                )

                try:
                    # Enforce task timeout
                    envelope = await asyncio.wait_for(
                        worker.execute(request),
                        timeout=float(node.timeout_seconds),
                    )
                except TimeoutError:
                    err = AgentError(
                        error_code="TIMEOUT",
                        error_type="TaskTimeout",
                        message=f"Subtask '{subtask_id}' timed out after {node.timeout_seconds}s",
                        is_retryable=True,
                    )
                    envelope = WorkerResponseEnvelope(
                        envelope_id=f"env_{uuid.uuid4().hex[:12]}",
                        dispatch_id=f"disp_{request.request_id}",
                        run_id=plan.run_id,
                        subtask_id=subtask_id,
                        status=TaskStatus.FAILED,
                        error=err,
                        worker_id=worker_id,
                    )
                except Exception as e:
                    err = AgentError(
                        error_code="WORKER_EXCEPTION",
                        error_type=e.__class__.__name__,
                        message=str(e),
                        is_retryable=True,
                    )
                    envelope = WorkerResponseEnvelope(
                        envelope_id=f"env_{uuid.uuid4().hex[:12]}",
                        dispatch_id=f"disp_{request.request_id}",
                        run_id=plan.run_id,
                        subtask_id=subtask_id,
                        status=TaskStatus.FAILED,
                        error=err,
                        worker_id=worker_id,
                    )

                # Process envelope status
                if envelope.status == TaskStatus.COMPLETED:
                    scheduler.mark_completed(subtask_id)
                    dur_ms = (
                        envelope.response.execution_time_ms if envelope.response else 0
                    )
                    tokens = (
                        envelope.response.token_usage
                        if envelope.response
                        else TokenUsage()
                    )
                    await self._emit_event(
                        TaskCompletedEvent(
                            run_id=plan.run_id,
                            subtask_id=subtask_id,
                            worker_id=worker_id,
                            duration_ms=dur_ms,
                            token_usage=tokens,
                        )
                    )
                    await self.observability_hook.on_task_completed(
                        plan.run_id, subtask_id, dur_ms, tokens
                    )
                    return envelope

                # Handle failure and check retry eligibility
                scheduler.mark_failed(
                    subtask_id, envelope.error.message if envelope.error else "Failed"
                )
                await self._emit_event(
                    TaskFailedEvent(
                        run_id=plan.run_id,
                        subtask_id=subtask_id,
                        worker_id=worker_id,
                        attempt=attempt,
                        error_code=envelope.error.error_code
                        if envelope.error
                        else "UNKNOWN",
                        error_message=envelope.error.message
                        if envelope.error
                        else "Unknown error",
                        is_retryable=envelope.error.is_retryable
                        if envelope.error
                        else False,
                    )
                )
                await self.observability_hook.on_task_failed(
                    plan.run_id,
                    subtask_id,
                    attempt,
                    envelope.error.message if envelope.error else "Failed",
                    envelope.error.is_retryable if envelope.error else False,
                )

                if self.retry_policy.should_retry(attempt, envelope.error):
                    next_attempt = attempt + 1
                    delay = self.retry_policy.calculate_delay(next_attempt)
                    scheduler.mark_retry_scheduled(subtask_id)

                    await self._emit_event(
                        TaskRetryScheduledEvent(
                            run_id=plan.run_id,
                            subtask_id=subtask_id,
                            failed_attempt=attempt,
                            next_attempt=next_attempt,
                            delay_seconds=delay,
                        )
                    )
                    await self.observability_hook.on_task_retried(
                        plan.run_id, subtask_id, next_attempt, delay
                    )

                    if delay > 0:
                        await self.sleeper(delay)

                    attempt += 1
                else:
                    # Retries exhausted or non-retryable
                    return envelope

            return envelope

    def _enforce_security_policy(self, node: SubtaskNode) -> None:
        """Validate agent role tool boundaries before dispatching task."""
        # Check that the assigned agent role has at least LLM_REASONING or required tools
        SecurityPolicy.enforce_permission(
            node.assigned_role, ToolPermission.LLM_REASONING
        )

    async def _emit_event(self, event: ExecutionEvent) -> None:
        """Publish lifecycle event to the configured event sink."""
        await self.event_sink.emit(event)

    async def _save_progress_checkpoint(
        self, plan: ResearchPlan, scheduler: DAGScheduler
    ) -> None:
        """Create and store execution state snapshot."""
        run_state = RunState(
            run_id=plan.run_id,
            goal=plan.goal,
            current_stage=RunStage.RESEARCHING,
            active_plan=plan,
            tasks=scheduler.get_all_task_states(),
        )
        snapshot = create_checkpoint(run_state)
        await self.checkpoint_repo.save_checkpoint(snapshot)

import uuid
from typing import Any, Final

from app.common.enums import AgentRole, TaskStatus, TaskType, ToolPermission
from app.common.errors import (
    EvidenceValidationError,
    PermissionDeniedError,
    ResearchMindError,
)
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol
from app.security.permissions import SecurityPolicy

# Canonical role-to-task compatibility matrix
ROLE_TASK_COMPATIBILITY: Final[dict[AgentRole, frozenset[TaskType]]] = {
    AgentRole.PLANNER: frozenset({TaskType.DECOMPOSITION}),
    AgentRole.RESEARCHER: frozenset(
        {
            TaskType.WEB_SEARCH,
            TaskType.ACADEMIC_SEARCH,
            TaskType.DOC_ANALYSIS,
        }
    ),
    AgentRole.ANALYST: frozenset({TaskType.SYNTHESIS}),
    AgentRole.VERIFIER: frozenset(
        {
            TaskType.VERIFICATION,
            TaskType.CONFLICT_DETECTION,
        }
    ),
    AgentRole.EVALUATOR: frozenset({TaskType.EVALUATION}),
    AgentRole.REPORTER: frozenset({TaskType.REPORTING}),
}

# Task-to-tool permission requirement mapping for least-privilege verification
TASK_REQUIRED_PERMISSIONS: Final[dict[TaskType, ToolPermission]] = {
    TaskType.DECOMPOSITION: ToolPermission.LLM_REASONING,
    TaskType.WEB_SEARCH: ToolPermission.WEB_SEARCH,
    TaskType.ACADEMIC_SEARCH: ToolPermission.ACADEMIC_SEARCH,
    TaskType.DOC_ANALYSIS: ToolPermission.DOC_EXTRACT,
    TaskType.SYNTHESIS: ToolPermission.LLM_REASONING,
    TaskType.VERIFICATION: ToolPermission.LLM_REASONING,
    TaskType.CONFLICT_DETECTION: ToolPermission.LLM_REASONING,
    TaskType.EVALUATION: ToolPermission.LLM_REASONING,
    TaskType.REPORTING: ToolPermission.LLM_REASONING,
}


class AgentWorkerRouter(WorkerProtocol):
    """Role- and TaskType-based worker dispatcher with SecurityPolicy validation and strict run isolation."""

    def __init__(
        self,
        security_policy: type[SecurityPolicy] | SecurityPolicy | None = None,
        cancellation_token: CancellationToken | None = None,
        router_id: str = "agent-worker-router-01",
    ) -> None:
        self.security_policy = security_policy or SecurityPolicy
        self.cancellation_token = cancellation_token
        self.router_id = router_id
        self._role_workers: dict[AgentRole, WorkerProtocol] = {}
        self._task_workers: dict[tuple[AgentRole, TaskType], WorkerProtocol] = {}

    def register_worker(
        self,
        worker: WorkerProtocol,
        role: AgentRole,
        task_types: tuple[TaskType, ...] | list[TaskType] | None = None,
    ) -> None:
        """Register a specialized worker for a given AgentRole and optional TaskTypes."""
        if not isinstance(worker, WorkerProtocol):
            raise TypeError(
                f"Expected WorkerProtocol implementation, got {type(worker).__name__}"
            )
        if not isinstance(role, AgentRole):
            raise TypeError(f"Expected AgentRole, got {type(role).__name__}")

        self._role_workers[role] = worker

        if task_types:
            for tt in task_types:
                if not isinstance(tt, TaskType):
                    raise TypeError(f"Expected TaskType, got {type(tt).__name__}")
                self._task_workers[(role, tt)] = worker

    def get_worker(
        self, role: AgentRole, task_type: TaskType | None = None
    ) -> WorkerProtocol | None:
        """Resolve worker for given role and optional task type."""
        if task_type is not None and (role, task_type) in self._task_workers:
            return self._task_workers[(role, task_type)]
        return self._role_workers.get(role)

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Validate request, enforce permissions, and dispatch to the matching specialized worker."""
        # 1. Validate run_id
        if not request.run_id or not request.run_id.strip():
            err = AgentError(
                error_code="INVALID_RUN_ID",
                error_type="EvidenceValidationError",
                message="run_id must not be empty or whitespace only",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)

        # 2. Check cooperative cancellation
        if self.cancellation_token and self.cancellation_token.is_cancelled:
            err = AgentError(
                error_code="CANCELLED",
                error_type="ExecutionCancelled",
                message=self.cancellation_token.reason or "Execution cancelled",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.CANCELLED)

        # 3. Validate AgentRole support
        if request.agent_role not in ROLE_TASK_COMPATIBILITY:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"Unsupported or unregistered agent role: '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)

        # 4. Validate TaskType compatibility with AgentRole
        compatible_tasks = ROLE_TASK_COMPATIBILITY[request.agent_role]
        if request.task_type not in compatible_tasks:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=(
                    f"TaskType '{request.task_type}' is not compatible with AgentRole '{request.agent_role}'. "
                    f"Supported tasks for '{request.agent_role}': {[t.value for t in compatible_tasks]}"
                ),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)

        # 5. SecurityPolicy permission check
        required_permission = TASK_REQUIRED_PERMISSIONS.get(request.task_type)
        if required_permission is not None:
            has_perm = SecurityPolicy.has_permission(
                request.agent_role, required_permission
            )
            if not has_perm:
                err = AgentError(
                    error_code="UNAUTHORIZED_DISPATCH",
                    error_type="PermissionDeniedError",
                    message=(
                        f"Role '{request.agent_role}' lacks required permission '{required_permission}' "
                        f"for task '{request.task_type}'"
                    ),
                    is_retryable=False,
                )
                return self._build_error_envelope(
                    request, err, status=TaskStatus.FAILED
                )

        # 6. Resolve registered worker
        worker = self.get_worker(request.agent_role, request.task_type)
        if worker is None:
            err = AgentError(
                error_code="WORKER_NOT_REGISTERED",
                error_type="KeyError",
                message=f"No worker registered for role '{request.agent_role}' and task '{request.task_type}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)

        # 7. Dispatch execution to target worker
        try:
            envelope: WorkerResponseEnvelope = await worker.execute(request)
            return envelope
        except (EvidenceValidationError, PermissionDeniedError) as e:
            err = AgentError(
                error_code="UNAUTHORIZED_DISPATCH",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)
        except ResearchMindError as e:
            err = AgentError(
                error_code="WORKER_EXECUTION_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)
        except Exception as e:
            err = AgentError(
                error_code="UNEXPECTED_ROUTER_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err, status=TaskStatus.FAILED)

    def _build_error_envelope(
        self,
        request: AgentRequest,
        error: AgentError,
        status: TaskStatus = TaskStatus.FAILED,
    ) -> WorkerResponseEnvelope:
        """Construct standardized failure or cancellation WorkerResponseEnvelope."""
        run_id = (
            request.run_id
            if request.run_id and request.run_id.strip()
            else "unknown_run"
        )
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{run_id}:{request.request_id}').hex[:12]}"
        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=run_id,
            subtask_id=request.subtask_id,
            agent_role=request.agent_role,
            output_data={},
            execution_time_ms=0,
            token_usage=TokenUsage(),
            error=error,
        )

        return WorkerResponseEnvelope(
            envelope_id=envelope_id,
            dispatch_id=f"disp_{request.request_id}",
            run_id=run_id,
            subtask_id=request.subtask_id,
            status=status,
            response=agent_response,
            error=error,
            worker_id=self.router_id,
        )


def create_default_worker_router(
    planner_worker: WorkerProtocol | None = None,
    researcher_worker: WorkerProtocol | None = None,
    analyst_worker: WorkerProtocol | None = None,
    verifier_worker: WorkerProtocol | None = None,
    evaluator_worker: WorkerProtocol | None = None,
    reporter_worker: WorkerProtocol | None = None,
    cancellation_token: CancellationToken | None = None,
    settings: Any = None,
) -> AgentWorkerRouter:
    """Instantiate and populate an AgentWorkerRouter with all default specialized agent workers."""
    from app.adapters.llm.factory import create_llm_client
    from app.agents.analyst.worker import AnalystWorker
    from app.agents.evaluator.worker import EvaluatorWorker
    from app.agents.planner.worker import PlannerWorker
    from app.agents.reporter.worker import ReporterWorker
    from app.agents.researcher.worker import ResearcherWorker
    from app.agents.verifier.worker import VerifierWorker
    from app.config.settings import get_settings
    from app.intelligence.planner import PlannerAgent
    from app.intelligence.reporter import ReporterAgent

    cfg = settings or get_settings()
    llm = create_llm_client(settings=cfg)

    router = AgentWorkerRouter(cancellation_token=cancellation_token)

    if planner_worker is None:
        if (
            settings is not None
            and getattr(settings, "llm_provider", "in_memory") == "gemini"
        ):
            planner_worker = PlannerWorker(planner_agent=PlannerAgent(llm_client=llm))
        else:
            planner_worker = PlannerWorker()

    if reporter_worker is None:
        if (
            settings is not None
            and getattr(settings, "llm_provider", "in_memory") == "gemini"
        ):
            reporter_worker = ReporterWorker(
                reporter_agent=ReporterAgent(llm_client=llm)
            )
        else:
            reporter_worker = ReporterWorker(reporter_agent=ReporterAgent())

    if researcher_worker is None and settings is not None:
        from app.adapters.search.factory import (
            create_academic_search_client,
            create_search_client,
        )
        from app.rag.factory import create_embedding_model, create_vector_store
        from app.rag.memory import VectorMemory

        search_client = create_search_client(settings=cfg)
        academic_search_client = create_academic_search_client(settings=cfg)
        embedding_model = create_embedding_model(settings=cfg)
        vector_store = create_vector_store(settings=cfg)
        vector_memory = VectorMemory(
            vector_store=vector_store,
            embedding_model=embedding_model,
        )
        researcher_worker = ResearcherWorker(
            search_client=search_client,
            academic_search_client=academic_search_client,
            vector_memory=vector_memory,
        )

    router.register_worker(
        planner_worker or PlannerWorker(),
        role=AgentRole.PLANNER,
        task_types=(TaskType.DECOMPOSITION,),
    )
    router.register_worker(
        researcher_worker or ResearcherWorker(),
        role=AgentRole.RESEARCHER,
        task_types=(
            TaskType.WEB_SEARCH,
            TaskType.ACADEMIC_SEARCH,
            TaskType.DOC_ANALYSIS,
        ),
    )
    router.register_worker(
        analyst_worker or AnalystWorker(),
        role=AgentRole.ANALYST,
        task_types=(TaskType.SYNTHESIS,),
    )
    router.register_worker(
        verifier_worker or VerifierWorker(),
        role=AgentRole.VERIFIER,
        task_types=(
            TaskType.VERIFICATION,
            TaskType.CONFLICT_DETECTION,
        ),
    )
    router.register_worker(
        evaluator_worker or EvaluatorWorker(),
        role=AgentRole.EVALUATOR,
        task_types=(TaskType.EVALUATION,),
    )
    router.register_worker(
        reporter_worker or ReporterWorker(),
        role=AgentRole.REPORTER,
        task_types=(TaskType.REPORTING,),
    )

    return router


__all__ = [
    "ROLE_TASK_COMPATIBILITY",
    "TASK_REQUIRED_PERMISSIONS",
    "AgentWorkerRouter",
    "create_default_worker_router",
]

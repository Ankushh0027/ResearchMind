"""Unit tests for Phase 4.2 AgentWorkerRouter."""

from typing import Any

import pytest

from app.agents.analyst.worker import AnalystWorker
from app.agents.evaluator.worker import EvaluatorWorker
from app.agents.planner.worker import PlannerWorker
from app.agents.reporter.worker import ReporterWorker
from app.agents.researcher.worker import ResearcherWorker
from app.agents.verifier.worker import VerifierWorker
from app.common.enums import (
    AgentRole,
    SourceTrustLevel,
    TaskStatus,
    TaskType,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.intelligence.models import CitationReference, KeyFinding
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol
from app.orchestration.router import (
    AgentWorkerRouter,
    create_default_worker_router,
)


class SpyWorker(WorkerProtocol):
    """Spy worker tracking execution invocations and payload arguments."""

    def __init__(self, worker_id: str = "spy-01") -> None:
        self.worker_id = worker_id
        self.invoked_requests: list[AgentRequest] = []

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        self.invoked_requests.append(request)
        resp = AgentResponse(
            response_id=f"resp_spy_{request.request_id}",
            request_id=request.request_id,
            run_id=request.run_id,
            subtask_id=request.subtask_id,
            agent_role=request.agent_role,
            output_data={"executed_by": self.worker_id},
            execution_time_ms=5,
            token_usage=TokenUsage(),
            error=None,
        )
        return WorkerResponseEnvelope(
            envelope_id=f"env_spy_{request.request_id}",
            dispatch_id=f"disp_{request.request_id}",
            run_id=request.run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.COMPLETED,
            response=resp,
            error=None,
            worker_id=self.worker_id,
        )


def _make_request(
    request_id: str = "req_rt_001",
    run_id: str = "run_rt_01",
    subtask_id: str = "task_rt_01",
    agent_role: AgentRole = AgentRole.PLANNER,
    task_type: TaskType = TaskType.DECOMPOSITION,
    goal_context: str = "Superconductivity research inquiry",
    input_data: dict[str, Any] | None = None,
) -> AgentRequest:
    return AgentRequest(
        request_id=request_id,
        run_id=run_id,
        subtask_id=subtask_id,
        agent_role=agent_role,
        task_type=task_type,
        goal_context=goal_context,
        input_data=input_data or {},
        idempotency_key="idem_rt_001",
    )


def test_router_protocol_compliance() -> None:
    """Test 1: Verify AgentWorkerRouter implements WorkerProtocol."""
    router = AgentWorkerRouter()
    assert isinstance(router, WorkerProtocol)


def test_default_router_creation_and_registration() -> None:
    """Test 2: Verify create_default_worker_router registers all 6 specialized workers."""
    router = create_default_worker_router()

    assert isinstance(router.get_worker(AgentRole.PLANNER), PlannerWorker)
    assert isinstance(router.get_worker(AgentRole.RESEARCHER), ResearcherWorker)
    assert isinstance(router.get_worker(AgentRole.ANALYST), AnalystWorker)
    assert isinstance(router.get_worker(AgentRole.VERIFIER), VerifierWorker)
    assert isinstance(router.get_worker(AgentRole.EVALUATOR), EvaluatorWorker)
    assert isinstance(router.get_worker(AgentRole.REPORTER), ReporterWorker)


@pytest.mark.parametrize(
    ("role", "task_type"),
    [
        (AgentRole.PLANNER, TaskType.DECOMPOSITION),
        (AgentRole.RESEARCHER, TaskType.WEB_SEARCH),
        (AgentRole.RESEARCHER, TaskType.ACADEMIC_SEARCH),
        (AgentRole.RESEARCHER, TaskType.DOC_ANALYSIS),
        (AgentRole.ANALYST, TaskType.SYNTHESIS),
        (AgentRole.VERIFIER, TaskType.VERIFICATION),
        (AgentRole.VERIFIER, TaskType.CONFLICT_DETECTION),
        (AgentRole.EVALUATOR, TaskType.EVALUATION),
        (AgentRole.REPORTER, TaskType.REPORTING),
    ],
)
@pytest.mark.asyncio
async def test_valid_role_and_task_dispatch(
    role: AgentRole, task_type: TaskType
) -> None:
    """Test 3: Verify all canonical role and task combinations route to the correct registered worker."""
    router = AgentWorkerRouter()
    spy = SpyWorker(worker_id=f"spy_{role.value}")
    router.register_worker(spy, role=role, task_types=(task_type,))

    req = _make_request(
        agent_role=role,
        task_type=task_type,
    )

    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    assert envelope.response.output_data["executed_by"] == f"spy_{role.value}"
    assert len(spy.invoked_requests) == 1
    assert spy.invoked_requests[0].request_id == req.request_id


@pytest.mark.parametrize(
    ("role", "incompatible_task"),
    [
        (AgentRole.ANALYST, TaskType.WEB_SEARCH),
        (AgentRole.RESEARCHER, TaskType.REPORTING),
        (AgentRole.REPORTER, TaskType.SYNTHESIS),
        (AgentRole.PLANNER, TaskType.VERIFICATION),
        (AgentRole.VERIFIER, TaskType.DECOMPOSITION),
        (AgentRole.EVALUATOR, TaskType.ACADEMIC_SEARCH),
    ],
)
@pytest.mark.asyncio
async def test_incompatible_role_task_rejection(
    role: AgentRole, incompatible_task: TaskType
) -> None:
    """Test 4: Verify incompatible role and task combinations are rejected before worker invocation."""
    router = AgentWorkerRouter()
    spy = SpyWorker(worker_id=f"spy_{role.value}")
    router.register_worker(spy, role=role)

    req = _make_request(agent_role=role, task_type=incompatible_task)
    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_TASK_TYPE"
    assert envelope.error.is_retryable is False
    assert len(spy.invoked_requests) == 0


@pytest.mark.asyncio
async def test_empty_run_id_rejection() -> None:
    """Test 5: Verify invalid/empty run_id is rejected with INVALID_RUN_ID."""
    router = AgentWorkerRouter()
    spy = SpyWorker()
    router.register_worker(
        spy, role=AgentRole.PLANNER, task_types=(TaskType.DECOMPOSITION,)
    )

    req = _make_request(run_id="   ")
    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_RUN_ID"
    assert envelope.error.is_retryable is False
    assert len(spy.invoked_requests) == 0


@pytest.mark.asyncio
async def test_unregistered_worker_rejection() -> None:
    """Test 6: Verify request for unregistered worker role fails with WORKER_NOT_REGISTERED."""
    router = AgentWorkerRouter()
    req = _make_request(
        agent_role=AgentRole.PLANNER,
        task_type=TaskType.DECOMPOSITION,
    )

    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "WORKER_NOT_REGISTERED"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cooperative_cancellation_enforcement() -> None:
    """Test 7: Verify router returns CANCELLED when cancellation_token is signalled."""
    token = CancellationToken()
    token.cancel(reason="User requested cancellation")

    router = AgentWorkerRouter(cancellation_token=token)
    spy = SpyWorker()
    router.register_worker(
        spy, role=AgentRole.PLANNER, task_types=(TaskType.DECOMPOSITION,)
    )

    req = _make_request()
    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.CANCELLED
    assert envelope.error is not None
    assert envelope.error.error_code == "CANCELLED"
    assert len(spy.invoked_requests) == 0


@pytest.mark.asyncio
async def test_worker_failure_envelope_preservation() -> None:
    """Test 8: Verify failed worker envelopes and error information are preserved."""

    class FailingWorker(WorkerProtocol):
        async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
            err = AgentError(
                error_code="ANALYSIS_TIMEOUT",
                error_type="TimeoutError",
                message="Analysis timeout exceeded",
                is_retryable=True,
            )
            return WorkerResponseEnvelope(
                envelope_id="env_failed_01",
                dispatch_id=f"disp_{request.request_id}",
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                status=TaskStatus.FAILED,
                error=err,
                worker_id="failing-worker",
            )

    router = AgentWorkerRouter()
    router.register_worker(
        FailingWorker(), role=AgentRole.ANALYST, task_types=(TaskType.SYNTHESIS,)
    )

    req = _make_request(agent_role=AgentRole.ANALYST, task_type=TaskType.SYNTHESIS)
    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "ANALYSIS_TIMEOUT"
    assert envelope.error.is_retryable is True


@pytest.mark.asyncio
async def test_worker_unexpected_exception_boundary() -> None:
    """Test 9: Verify unexpected worker exception is trapped into a structured failure envelope."""

    class CrashingWorker(WorkerProtocol):
        async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
            _ = request
            raise RuntimeError("Unexpected memory segmentation fault")

    router = AgentWorkerRouter()
    router.register_worker(
        CrashingWorker(), role=AgentRole.PLANNER, task_types=(TaskType.DECOMPOSITION,)
    )

    req = _make_request()
    envelope = await router.execute(req)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNEXPECTED_ROUTER_ERROR"
    assert envelope.error.is_retryable is True


@pytest.mark.asyncio
async def test_multi_tenant_run_isolation() -> None:
    """Test 10: Verify multi-tenant requests (run_A vs run_B) execute in strict isolation."""
    router = create_default_worker_router()

    req_a = _make_request(
        request_id="req_A",
        run_id="run_tenant_A",
        subtask_id="task_A",
        agent_role=AgentRole.PLANNER,
        task_type=TaskType.DECOMPOSITION,
    )
    req_b = _make_request(
        request_id="req_B",
        run_id="run_tenant_B",
        subtask_id="task_B",
        agent_role=AgentRole.PLANNER,
        task_type=TaskType.DECOMPOSITION,
    )

    env_a = await router.execute(req_a)
    env_b = await router.execute(req_b)

    assert env_a.status == TaskStatus.COMPLETED
    assert env_a.run_id == "run_tenant_A"
    assert env_a.subtask_id == "task_A"

    assert env_b.status == TaskStatus.COMPLETED
    assert env_b.run_id == "run_tenant_B"
    assert env_b.subtask_id == "task_B"


@pytest.mark.asyncio
async def test_integration_all_default_workers_dispatch() -> None:
    """Test 11 Integration: Verify all 6 default workers execute successfully through router."""
    router = create_default_worker_router()
    run_id = "run_integration_router_01"

    # 1. Planner
    req_plan = _make_request(
        request_id="req_p",
        run_id=run_id,
        agent_role=AgentRole.PLANNER,
        task_type=TaskType.DECOMPOSITION,
        goal_context="Analyze cuprate superconductivity",
    )
    env_plan = await router.execute(req_plan)
    assert env_plan.status == TaskStatus.COMPLETED
    assert env_plan.response is not None

    # 2. Researcher
    req_res = _make_request(
        request_id="req_r",
        run_id=run_id,
        agent_role=AgentRole.RESEARCHER,
        task_type=TaskType.WEB_SEARCH,
        input_data={"queries": ["cuprate superconductivity"]},
    )
    env_res = await router.execute(req_res)
    assert env_res.status == TaskStatus.COMPLETED
    assert env_res.response is not None

    # 3. Analyst
    prov = SourceProvenance.from_content(
        raw_content="Electronic nematicity characterizes cuprates.",
        title="Study 2026",
        source_url="https://nature.com/articles/cuprates",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )
    ev = EvidenceRecord(
        evidence_id="ev_01",
        run_id=run_id,
        provenance=prov,
        content_hash=prov.content_hash,
        normalized_content="Electronic nematicity characterizes cuprates.",
    )
    req_an = _make_request(
        request_id="req_a",
        run_id=run_id,
        agent_role=AgentRole.ANALYST,
        task_type=TaskType.SYNTHESIS,
        input_data={"evidence_records": [ev.model_dump()]},
    )
    env_an = await router.execute(req_an)
    assert env_an.status == TaskStatus.COMPLETED
    assert env_an.response is not None

    # 4. Verifier
    claim = ExtractedClaim(
        claim_id="clm_01",
        run_id=run_id,
        statement="Electronic nematicity characterizes cuprates.",
        supporting_evidence_ids=("ev_01",),
        confidence_score=0.95,
    )
    req_ver = _make_request(
        request_id="req_v",
        run_id=run_id,
        agent_role=AgentRole.VERIFIER,
        task_type=TaskType.VERIFICATION,
        input_data={
            "claims": [claim.model_dump()],
            "evidence_records": [ev.model_dump()],
        },
    )
    env_ver = await router.execute(req_ver)
    assert env_ver.status == TaskStatus.COMPLETED
    assert env_ver.response is not None

    # 5. Evaluator
    finding = KeyFinding(
        finding_id="fnd_01",
        run_id=run_id,
        title="Cuprate Electronic Nematicity",
        narrative="Electronic nematicity characterizes cuprates.",
        claim_ids=("clm_01",),
        evidence_ids=("ev_01",),
    )
    citation = CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://nature.com/articles/cuprates",
        title="Study 2026",
        domain="nature.com",
        run_id=run_id,
    )
    req_eval = _make_request(
        request_id="req_e",
        run_id=run_id,
        agent_role=AgentRole.EVALUATOR,
        task_type=TaskType.EVALUATION,
        goal_context="Analyze cuprate superconductivity",
        input_data={
            "goal_query": "Analyze cuprate superconductivity",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
        },
    )
    env_eval = await router.execute(req_eval)
    assert env_eval.status == TaskStatus.COMPLETED
    assert env_eval.response is not None

    # 6. Reporter
    req_rep = _make_request(
        request_id="req_rep",
        run_id=run_id,
        agent_role=AgentRole.REPORTER,
        task_type=TaskType.REPORTING,
        goal_context="Analyze cuprate superconductivity",
        input_data={
            "goal_query": "Analyze cuprate superconductivity",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
            "evaluation": env_eval.response.output_data,
        },
    )
    env_rep = await router.execute(req_rep)
    assert env_rep.status == TaskStatus.COMPLETED
    assert env_rep.response is not None
    assert "markdown_report" in env_rep.response.output_data

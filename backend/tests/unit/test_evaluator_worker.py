"""Unit tests for Phase 4.1.5 EvaluatorWorker adapter."""

from typing import Any

import pytest

from app.agents.evaluator.worker import (
    SUPPORTED_EVALUATOR_TASK_TYPES,
    EvaluatorWorker,
)
from app.common.enums import (
    AgentRole,
    SourceTrustLevel,
    TaskStatus,
    TaskType,
)
from app.common.errors import EvaluationError
from app.intelligence.claims import ExtractedClaim
from app.intelligence.evaluator import EvaluatorAgent
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    KeyFinding,
)
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.protocols import WorkerProtocol


def _make_finding(
    finding_id: str = "fnd_01",
    run_id: str = "run_eval_01",
    title: str = "Quantum Error Correction Thresholds",
    narrative: str = "Surface codes demonstrate fault-tolerant quantum error suppression below threshold.",
    claim_ids: tuple[str, ...] = ("clm_01",),
    evidence_ids: tuple[str, ...] = ("ev_01",),
) -> KeyFinding:
    return KeyFinding(
        finding_id=finding_id,
        run_id=run_id,
        title=title,
        narrative=narrative,
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
    )


def _make_claim(
    claim_id: str = "clm_01",
    run_id: str = "run_eval_01",
    statement: str = "Surface codes demonstrate fault-tolerant error suppression below threshold.",
    evidence_ids: tuple[str, ...] = ("ev_01",),
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        run_id=run_id,
        statement=statement,
        supporting_evidence_ids=evidence_ids,
        confidence_score=0.95,
    )


def _make_citation(
    citation_key: str = "[CIT-01]",
    evidence_id: str = "ev_01",
    run_id: str = "run_eval_01",
) -> CitationReference:
    return CitationReference(
        citation_key=citation_key,
        evidence_id=evidence_id,
        source_url="https://nature.com/articles/quantum-error-correction",
        title="Fault-Tolerant Quantum Error Suppression",
        domain="nature.com",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        run_id=run_id,
    )


def _make_evaluator_request(
    request_id: str = "req_eval_001",
    run_id: str = "run_eval_01",
    subtask_id: str = "task_eval_01",
    agent_role: AgentRole = AgentRole.EVALUATOR,
    task_type: TaskType = TaskType.EVALUATION,
    goal_context: str = "Evaluate quantum error correction thresholds and fidelity",
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
        idempotency_key="idem_eval_001",
    )


def test_evaluator_worker_protocol_compliance() -> None:
    """Test 1: Verify EvaluatorWorker implements WorkerProtocol and supports expected task types."""
    worker = EvaluatorWorker()
    assert isinstance(worker, WorkerProtocol)
    assert TaskType.EVALUATION in SUPPORTED_EVALUATOR_TASK_TYPES


@pytest.mark.asyncio
async def test_successful_evaluation_execution() -> None:
    """Test 2: Verify EvaluatorWorker executes evaluation and emits structured EvaluationReport."""
    worker = EvaluatorWorker()
    finding = _make_finding()
    claim = _make_claim()
    citation = _make_citation()

    request = _make_evaluator_request(
        input_data={
            "goal_query": "Quantum error correction thresholds and fidelity",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
            "contradictions": [],
        }
    )

    envelope: WorkerResponseEnvelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.run_id == "run_eval_01"
    assert envelope.subtask_id == "task_eval_01"
    assert envelope.response is not None
    assert envelope.response.is_success is True

    output = envelope.response.output_data
    assert "overall_score" in output
    assert "passed" in output
    assert "rubric_scores" in output
    assert "completeness_score" in output
    assert "citation_coverage_score" in output
    assert output["passed"] is True


@pytest.mark.asyncio
async def test_unsupported_role_rejection() -> None:
    """Test 3: Verify request with unsupported agent role fails with UNSUPPORTED_ROLE."""
    worker = EvaluatorWorker()
    request = _make_evaluator_request(agent_role=AgentRole.ANALYST)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_ROLE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_unsupported_task_type_rejection() -> None:
    """Test 4: Verify request with unsupported task type fails with UNSUPPORTED_TASK_TYPE."""
    worker = EvaluatorWorker()
    request = _make_evaluator_request(task_type=TaskType.SYNTHESIS)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_TASK_TYPE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_empty_run_id_rejection() -> None:
    """Test 5: Verify empty run_id fails with INVALID_RUN_ID."""
    worker = EvaluatorWorker()
    request = _make_evaluator_request(run_id="   ")

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_RUN_ID"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_missing_goal_query_rejection() -> None:
    """Test 6: Verify missing/empty goal query fails with EVALUATION_ERROR."""
    worker = EvaluatorWorker()
    request = _make_evaluator_request(
        goal_context="Non-empty placeholder",
        input_data={"goal_query": "   "},
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "EVALUATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cross_run_finding_rejection() -> None:
    """Test 7: Verify foreign-run finding fails with EVALUATION_INPUT_VALIDATION_ERROR."""
    worker = EvaluatorWorker()
    foreign_finding = _make_finding(
        finding_id="fnd_foreign",
        run_id="run_foreign_tenant",
    )

    request = _make_evaluator_request(
        run_id="run_eval_01",
        input_data={
            "goal_query": "Quantum error correction",
            "findings": [foreign_finding.model_dump()],
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "EVALUATION_INPUT_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cross_run_citation_rejection() -> None:
    """Test 8: Verify foreign-run citation fails with EVALUATION_INPUT_VALIDATION_ERROR."""
    worker = EvaluatorWorker()
    foreign_cit = _make_citation(
        citation_key="[CIT-99]",
        run_id="run_foreign_tenant",
    )

    request = _make_evaluator_request(
        run_id="run_eval_01",
        input_data={
            "goal_query": "Quantum error correction",
            "citations": [foreign_cit.model_dump()],
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "EVALUATION_INPUT_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_evaluator_error_mapping() -> None:
    """Test 9: Verify EvaluationError maps to EVALUATION_ERROR with is_retryable=False."""

    class FaultyEvaluatorAgent(EvaluatorAgent):
        async def evaluate_research(
            self,
            goal_query: str,
            findings: list[KeyFinding],
            claims: list[ExtractedClaim],
            citations: list[CitationReference],
            contradictions: list[ContradictionItem],
            run_id: str,
            plan_id: str = "plan_default",
        ) -> Any:
            _ = (
                goal_query,
                findings,
                claims,
                citations,
                contradictions,
                run_id,
                plan_id,
            )
            raise EvaluationError(
                "Evaluation rubric calculation failed", code="RUBRIC_FAILED"
            )

    worker = EvaluatorWorker(evaluator_agent=FaultyEvaluatorAgent())
    request = _make_evaluator_request(
        input_data={"goal_query": "Quantum error correction"}
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "EVALUATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_deterministic_output_and_identifiers() -> None:
    """Test 10: Verify repeated execution produces identical deterministic IDs."""
    worker = EvaluatorWorker()
    finding = _make_finding()
    claim = _make_claim()
    citation = _make_citation()

    request = _make_evaluator_request(
        run_id="run_det_eval",
        input_data={
            "goal_query": "Quantum error correction",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
        },
    )

    env1 = await worker.execute(request)
    env2 = await worker.execute(request)

    assert env1.envelope_id == env2.envelope_id
    assert env1.response is not None and env2.response is not None
    assert env1.response.response_id == env2.response.response_id


@pytest.mark.asyncio
async def test_integration_research_evaluation_chain() -> None:
    """Test 11 Integration: Verify findings + claims + citations + contradictions -> EvaluatorWorker -> EvaluationReport."""
    eval_agent = EvaluatorAgent(pass_threshold=0.60)
    worker = EvaluatorWorker(evaluator_agent=eval_agent)

    finding = _make_finding(
        title="High-Temperature Cuprate Superconductivity",
        narrative="Electronic nematicity and d-wave pairing characterize high-Tc superconductivity in cuprate layers.",
    )
    claim = _make_claim(
        statement="Electronic nematicity and d-wave pairing characterize high-Tc superconductivity in cuprate layers."
    )
    citation = _make_citation()
    contradiction = ContradictionItem(
        item_id="cnt_01",
        run_id="run_eval_01",
        description="Competing pairing symmetry hypotheses",
        divergence_analysis="Divergent assertions regarding s-wave vs d-wave pairing",
        conflicting_claim_ids=("clm_01", "clm_02"),
        severity_score=0.3,
    )

    request = _make_evaluator_request(
        input_data={
            "goal_query": "High-temperature cuprate superconductivity mechanisms",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
            "contradictions": [contradiction.model_dump()],
        }
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["overall_score"] > 0.0
    assert output["passed"] is True
    assert len(output["rubric_scores"]) >= 4

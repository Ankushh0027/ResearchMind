"""Unit tests for Phase 4.1.6 ReporterWorker adapter."""

from typing import Any

import pytest

from app.agents.reporter.worker import (
    SUPPORTED_REPORTER_TASK_TYPES,
    ReporterWorker,
)
from app.common.enums import (
    AgentRole,
    SourceTrustLevel,
    TaskStatus,
    TaskType,
)
from app.common.errors import ReportingError
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
)
from app.intelligence.reporter import ReporterAgent
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.protocols import WorkerProtocol


def _make_finding(
    finding_id: str = "fnd_01",
    run_id: str = "run_rep_01",
    title: str = "Cuprate High-Tc Superconductivity",
    narrative: str = "Electronic nematicity and d-wave symmetry govern superconducting transition temperatures.",
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
    run_id: str = "run_rep_01",
    statement: str = "Electronic nematicity and d-wave symmetry govern superconducting transition temperatures.",
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
    run_id: str = "run_rep_01",
) -> CitationReference:
    return CitationReference(
        citation_key=citation_key,
        evidence_id=evidence_id,
        source_url="https://nature.com/articles/cuprates-2026",
        title="Electronic Nematicity in Cuprate Superconductors",
        domain="nature.com",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        run_id=run_id,
    )


def _make_evaluation_report(
    run_id: str = "run_rep_01",
    report_id: str = "eval_01",
) -> EvaluationReport:
    return EvaluationReport(
        report_id=report_id,
        run_id=run_id,
        plan_id="plan_rep_01",
        passed=True,
        overall_score=0.88,
        completeness_score=0.90,
        citation_coverage_score=0.85,
        contradiction_rate=0.0,
        unsupported_claim_rate=0.0,
        source_diversity_score=0.80,
        rubric_scores=(
            EvaluationRubricScore(
                rubric_name="Completeness",
                score=0.90,
                feedback="Rigorous domain inquiry coverage.",
            ),
        ),
        summary_critique="High quality research synthesis with robust citation backing.",
    )


def _make_reporter_request(
    request_id: str = "req_rep_001",
    run_id: str = "run_rep_01",
    subtask_id: str = "task_rep_01",
    agent_role: AgentRole = AgentRole.REPORTER,
    task_type: TaskType = TaskType.REPORTING,
    goal_context: str = "Compile comprehensive research dossier on cuprate superconductivity",
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
        idempotency_key="idem_rep_001",
    )


def test_reporter_worker_protocol_compliance() -> None:
    """Test 1: Verify ReporterWorker implements WorkerProtocol and supports expected task types."""
    worker = ReporterWorker()
    assert isinstance(worker, WorkerProtocol)
    assert TaskType.REPORTING in SUPPORTED_REPORTER_TASK_TYPES


@pytest.mark.asyncio
async def test_successful_dossier_compilation() -> None:
    """Test 2: Verify ReporterWorker compiles verified findings, citations, and evaluation into a ResearchDossier."""
    worker = ReporterWorker()
    finding = _make_finding()
    claim = _make_claim()
    citation = _make_citation()
    evaluation = _make_evaluation_report()

    request = _make_reporter_request(
        input_data={
            "goal_query": "Cuprate Superconductivity Mechanisms",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
            "contradictions": [],
            "evaluation": evaluation.model_dump(),
            "methodology_summary": "Hermetic deterministic synthesis",
        }
    )

    envelope: WorkerResponseEnvelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.run_id == "run_rep_01"
    assert envelope.subtask_id == "task_rep_01"
    assert envelope.response is not None
    assert envelope.response.is_success is True

    output = envelope.response.output_data
    assert "dossier_id" in output
    assert "markdown_report" in output
    assert output["goal_query"] == "Cuprate Superconductivity Mechanisms"
    assert len(output["key_findings"]) == 1
    assert len(output["citations"]) == 1
    assert output["evaluation"]["overall_score"] == 0.88

    # Verify Markdown contains core headings
    md = output["markdown_report"]
    assert "# Research Dossier: Cuprate Superconductivity Mechanisms" in md
    assert "## Executive Summary" in md
    assert "## Key Thematic Findings" in md
    assert "## Comprehensive Bibliography & Sources" in md
    assert "## Quality Audit & Self-Evaluation" in md


@pytest.mark.asyncio
async def test_unsupported_role_rejection() -> None:
    """Test 3: Verify request with unsupported agent role fails with UNSUPPORTED_ROLE."""
    worker = ReporterWorker()
    request = _make_reporter_request(agent_role=AgentRole.ANALYST)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_ROLE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_unsupported_task_type_rejection() -> None:
    """Test 4: Verify request with unsupported task type fails with UNSUPPORTED_TASK_TYPE."""
    worker = ReporterWorker()
    request = _make_reporter_request(task_type=TaskType.EVALUATION)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_TASK_TYPE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_empty_run_id_rejection() -> None:
    """Test 5: Verify empty run_id fails with INVALID_RUN_ID."""
    worker = ReporterWorker()
    request = _make_reporter_request(run_id="   ")

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_RUN_ID"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_missing_goal_query_rejection() -> None:
    """Test 6: Verify missing/empty goal query fails with REPORT_GENERATION_ERROR."""
    worker = ReporterWorker()
    request = _make_reporter_request(
        goal_context="Placeholder context",
        input_data={"goal_query": "   "},
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "REPORT_GENERATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cross_run_finding_rejection() -> None:
    """Test 7: Verify foreign-run finding fails with REPORT_INPUT_VALIDATION_ERROR."""
    worker = ReporterWorker()
    foreign_finding = _make_finding(
        finding_id="fnd_foreign",
        run_id="run_foreign_tenant",
    )

    request = _make_reporter_request(
        run_id="run_rep_01",
        input_data={
            "goal_query": "Cuprate Superconductivity",
            "findings": [foreign_finding.model_dump()],
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "REPORT_INPUT_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cross_run_evaluation_rejection() -> None:
    """Test 8: Verify foreign-run evaluation report fails with REPORT_INPUT_VALIDATION_ERROR."""
    worker = ReporterWorker()
    foreign_eval = _make_evaluation_report(run_id="run_foreign_tenant")

    request = _make_reporter_request(
        run_id="run_rep_01",
        input_data={
            "goal_query": "Cuprate Superconductivity",
            "evaluation": foreign_eval.model_dump(),
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "REPORT_INPUT_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_reporter_error_mapping() -> None:
    """Test 9: Verify ReportingError maps to REPORT_GENERATION_ERROR with is_retryable=False."""

    class FaultyReporterAgent(ReporterAgent):
        async def compile_dossier(
            self,
            goal_query: str,
            findings: list[KeyFinding],
            claims: list[ExtractedClaim],
            citations: list[CitationReference],
            contradictions: list[ContradictionItem],
            run_id: str,
            evaluation: EvaluationReport | None = None,
            methodology_summary: str = "",
            limitations: list[str] | None = None,
        ) -> Any:
            _ = (
                goal_query,
                findings,
                claims,
                citations,
                contradictions,
                run_id,
                evaluation,
                methodology_summary,
                limitations,
            )
            raise ReportingError(
                "Report formatting pipeline failure", code="FORMAT_FAILED"
            )

    worker = ReporterWorker(reporter_agent=FaultyReporterAgent())
    request = _make_reporter_request(
        input_data={"goal_query": "Cuprate Superconductivity"}
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "REPORT_GENERATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_deterministic_output_and_identifiers() -> None:
    """Test 10: Verify repeated execution produces identical deterministic IDs."""
    worker = ReporterWorker()
    finding = _make_finding()
    claim = _make_claim()
    citation = _make_citation()

    request = _make_reporter_request(
        run_id="run_det_rep",
        input_data={
            "goal_query": "Cuprate Superconductivity",
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
async def test_integration_full_dossier_pipeline() -> None:
    """Test 11 Integration: Verify findings + claims + citations + evaluation -> ReporterWorker -> publication-grade Markdown ResearchDossier."""
    agent = ReporterAgent()
    worker = ReporterWorker(reporter_agent=agent)

    finding = _make_finding()
    claim = _make_claim()
    citation = _make_citation()
    contradiction = ContradictionItem(
        item_id="cnt_01",
        run_id="run_rep_01",
        description="Competing theories regarding nematic transitions",
        divergence_analysis="Divergence in theoretical interpretation of lattice distortion vs spin fluctuation",
        conflicting_claim_ids=("clm_01", "clm_02"),
        severity_score=0.4,
    )
    evaluation = _make_evaluation_report()

    request = _make_reporter_request(
        input_data={
            "goal_query": "Cuprate Superconductivity Mechanisms",
            "findings": [finding.model_dump()],
            "claims": [claim.model_dump()],
            "citations": [citation.model_dump()],
            "contradictions": [contradiction.model_dump()],
            "evaluation": evaluation.model_dump(),
            "methodology_summary": "Topological multi-agent verification pipeline",
            "limitations": [
                "Requires further synchrotron verification at sub-10K temperatures."
            ],
        }
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert "dossier_id" in output
    assert len(output["markdown_report"]) > 500
    assert (
        "## Documented Contradictions & Divergent Perspectives"
        in output["markdown_report"]
    )
    assert "## Research Limitations" in output["markdown_report"]

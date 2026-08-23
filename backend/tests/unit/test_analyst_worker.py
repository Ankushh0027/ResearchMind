"""Unit tests for Phase 4.1.3 AnalystWorker adapter."""

from typing import Any

import pytest

from app.agents.analyst.worker import (
    SUPPORTED_ANALYST_TASK_TYPES,
    AnalystWorker,
)
from app.common.enums import AgentRole, SourceTrustLevel, TaskStatus, TaskType
from app.common.errors import AnalysisError
from app.intelligence.analyst import AnalystAgent
from app.intelligence.claims import DeterministicClaimExtractor, ExtractedClaim
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.protocols import WorkerProtocol
from app.rag.memory import VectorMemory


def _make_evidence_record(
    evidence_id: str = "ev_001",
    run_id: str = "run_an_01",
    content: str = "Grounded empirical trial shows 42% latency reduction under load.",
    trust_level: SourceTrustLevel = SourceTrustLevel.PEER_REVIEWED,
    is_untrusted: bool = False,
    is_quarantined: bool = False,
) -> EvidenceRecord:
    provenance = SourceProvenance.from_content(
        raw_content=content,
        title="Performance Study 2026",
        source_url="https://example.org/study",
        trust_level=trust_level,
    )
    return EvidenceRecord(
        evidence_id=evidence_id,
        run_id=run_id,
        provenance=provenance,
        content_hash=provenance.content_hash,
        normalized_content=content,
        is_untrusted=is_untrusted,
        is_quarantined=is_quarantined,
    )


def _make_analyst_request(
    request_id: str = "req_an_001",
    run_id: str = "run_an_01",
    subtask_id: str = "task_synth_01",
    agent_role: AgentRole = AgentRole.ANALYST,
    task_type: TaskType = TaskType.SYNTHESIS,
    goal_context: str = "Synthesize performance evaluation benchmarks",
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
        idempotency_key="idem_an_001",
    )


def test_analyst_worker_protocol_compliance() -> None:
    """Test 1: Verify AnalystWorker implements WorkerProtocol."""
    worker = AnalystWorker()
    assert isinstance(worker, WorkerProtocol)
    assert TaskType.SYNTHESIS in SUPPORTED_ANALYST_TASK_TYPES


@pytest.mark.asyncio
async def test_successful_synthesis_from_evidence_records() -> None:
    """Test 2, 3, 4, 5: Verify synthesis pipeline from EvidenceRecord to ExtractedClaim and KeyFinding."""
    worker = AnalystWorker()
    rec1 = _make_evidence_record(
        evidence_id="ev_01",
        content="Engineered Cas9 enzymes yield higher on-target fidelity in mammalian cells.",
    )
    rec2 = _make_evidence_record(
        evidence_id="ev_02",
        content="Off-target indel rates drop below 0.1 percent with high-fidelity Cas9 variants.",
    )

    request = _make_analyst_request(
        input_data={
            "evidence_records": [rec1.model_dump(), rec2.model_dump()],
            "research_goal": "Evaluate CRISPR Cas9 off-target fidelity improvements",
        }
    )

    envelope: WorkerResponseEnvelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.run_id == "run_an_01"
    assert envelope.subtask_id == "task_synth_01"
    assert envelope.error is None
    assert envelope.response is not None
    assert envelope.response.is_success is True

    output = envelope.response.output_data
    assert output["total_claims"] >= 2
    assert output["total_findings"] >= 1
    assert len(output["claims"]) >= 2
    assert len(output["findings"]) >= 1

    # Verify claim grounding
    claims = output["claims"]
    for c in claims:
        assert c["run_id"] == "run_an_01"
        assert len(c["supporting_evidence_ids"]) >= 1

    # Verify finding synthesis
    findings = output["findings"]
    for f in findings:
        assert f["run_id"] == "run_an_01"
        assert len(f["claim_ids"]) >= 1
        assert len(f["evidence_ids"]) >= 1


@pytest.mark.asyncio
async def test_synthesis_from_direct_pre_extracted_claims() -> None:
    """Test 6: Verify synthesis works directly when pre-extracted claims are supplied."""
    worker = AnalystWorker()
    claim1 = ExtractedClaim(
        claim_id="clm_01",
        run_id="run_an_01",
        statement="Superconducting qubits exhibit 100 microsecond coherence times.",
        supporting_evidence_ids=("ev_sc_01",),
        confidence_score=0.95,
        topic_tags=("quantum", "hardware"),
    )
    claim2 = ExtractedClaim(
        claim_id="clm_02",
        run_id="run_an_01",
        statement="Surface code error correction suppresses logical error rates below physical threshold.",
        supporting_evidence_ids=("ev_sc_02",),
        confidence_score=0.90,
        topic_tags=("quantum", "error_correction"),
    )

    request = _make_analyst_request(
        input_data={"claims": [claim1.model_dump(), claim2.model_dump()]}
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["total_claims"] == 2
    assert output["total_findings"] >= 1


@pytest.mark.asyncio
async def test_vector_memory_fallback_retrieval() -> None:
    """Test 7: Verify VectorMemory fallback retrieval when evidence_records are not passed directly."""
    vector_memory = VectorMemory()
    rec = _make_evidence_record(
        evidence_id="ev_mem_01",
        content="Transformer self-attention exhibits quadratic memory complexity with sequence length.",
    )
    await vector_memory.upsert_evidence([rec])

    worker = AnalystWorker(vector_memory=vector_memory)
    request = _make_analyst_request(
        goal_context="Transformer memory complexity",
        input_data={"query": "Transformer complexity"},
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["total_claims"] >= 1


@pytest.mark.asyncio
async def test_empty_evidence_handling() -> None:
    """Test 8: Verify empty evidence fails gracefully with ANALYSIS_ERROR without unhandled crash."""
    worker = AnalystWorker()
    request = _make_analyst_request(input_data={"evidence_records": []})

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "ANALYSIS_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_unsupported_role_rejection() -> None:
    """Test 10: Verify request with unsupported agent role fails with UNSUPPORTED_ROLE."""
    worker = AnalystWorker()
    request = _make_analyst_request(agent_role=AgentRole.RESEARCHER)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_ROLE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_unsupported_task_type_rejection() -> None:
    """Test 11: Verify request with unsupported task type fails with UNSUPPORTED_TASK_TYPE."""
    worker = AnalystWorker()
    request = _make_analyst_request(task_type=TaskType.WEB_SEARCH)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_TASK_TYPE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_empty_run_id_rejection() -> None:
    """Test 8: Verify empty run_id fails with INVALID_RUN_ID."""
    worker = AnalystWorker()
    request = _make_analyst_request(run_id="   ")

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_RUN_ID"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cross_run_evidence_rejection() -> None:
    """Test 9: Verify evidence record with mismatched run_id is rejected with EVIDENCE_VALIDATION_ERROR."""
    worker = AnalystWorker()
    foreign_rec = _make_evidence_record(
        evidence_id="ev_foreign",
        run_id="run_foreign_tenant",
        content="Foreign tenant confidential benchmark data.",
    )

    request = _make_analyst_request(
        run_id="run_an_01",
        input_data={"evidence_records": [foreign_rec.model_dump()]},
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "EVIDENCE_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_untrusted_and_quarantined_provenance_preservation() -> None:
    """Test 13: Verify is_untrusted and is_quarantined flags propagate from evidence to extracted claims."""
    worker = AnalystWorker()
    quarantined_rec = _make_evidence_record(
        evidence_id="ev_quar_01",
        content="Sanitized proposition text without active malicious instructions.",
        is_untrusted=True,
        is_quarantined=True,
    )

    request = _make_analyst_request(
        input_data={"evidence_records": [quarantined_rec.model_dump()]}
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    claims = envelope.response.output_data["claims"]
    assert len(claims) >= 1
    assert all(c["is_quarantined"] is True for c in claims)
    assert all(c["is_untrusted"] is True for c in claims)


@pytest.mark.asyncio
async def test_analysis_error_mapping() -> None:
    """Test 12: Verify AnalysisError maps to ANALYSIS_ERROR with is_retryable=False."""

    class FaultyAnalystAgent(AnalystAgent):
        async def analyze_claims(
            self,
            claims: list[ExtractedClaim],
            run_id: str,
            research_goal: str = "",
        ) -> Any:
            _ = (claims, run_id, research_goal)
            raise AnalysisError("Thematic clustering constraint failed")

    worker = AnalystWorker(analyst_agent=FaultyAnalystAgent())
    rec = _make_evidence_record(
        evidence_id="ev_01",
        content="Valid evidence sentence for extraction.",
    )
    request = _make_analyst_request(input_data={"evidence_records": [rec.model_dump()]})

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "ANALYSIS_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_deterministic_output_and_identifiers() -> None:
    """Test 14: Verify repeated execution with identical request produces identical deterministic envelope IDs."""
    worker = AnalystWorker()
    rec = _make_evidence_record()
    request = _make_analyst_request(
        run_id="run_det_an",
        input_data={"evidence_records": [rec.model_dump()]},
    )

    env1 = await worker.execute(request)
    env2 = await worker.execute(request)

    assert env1.envelope_id == env2.envelope_id
    assert env1.response is not None and env2.response is not None
    assert env1.response.response_id == env2.response.response_id


@pytest.mark.asyncio
async def test_full_chain_integration() -> None:
    """Test 14 Integration: Verify EvidenceRecord -> DeterministicClaimExtractor -> AnalystWorker -> AnalystAgent -> KeyFinding."""
    extractor = DeterministicClaimExtractor()
    analyst = AnalystAgent()
    worker = AnalystWorker(claim_extractor=extractor, analyst_agent=analyst)

    rec = _make_evidence_record(
        evidence_id="ev_int_01",
        run_id="run_integration_01",
        content="Autonomous agent worker pipelines enable scalable multi-tenant execution.",
    )

    request = _make_analyst_request(
        run_id="run_integration_01",
        input_data={
            "evidence_records": [rec.model_dump()],
            "research_goal": "Scalable autonomous multi-tenant execution",
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["total_claims"] >= 1
    assert output["total_findings"] >= 1
    assert output["evidence_ids_covered"] == ["ev_int_01"]

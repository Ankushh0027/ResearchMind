"""Unit tests for Phase 4.1.4 VerifierWorker adapter."""

from typing import Any

import pytest

from app.agents.verifier.worker import (
    SUPPORTED_VERIFIER_TASK_TYPES,
    VerifierWorker,
)
from app.common.enums import (
    AgentRole,
    SourceTrustLevel,
    TaskStatus,
    TaskType,
    VerificationStatus,
)
from app.common.errors import VerificationError
from app.intelligence.claims import ExtractedClaim
from app.intelligence.contradiction import ContradictionDetector
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.intelligence.models import ContradictionItem
from app.intelligence.verifier import VerifierAgent
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.protocols import WorkerProtocol
from app.rag.memory import VectorMemory


def _make_evidence_record(
    evidence_id: str = "ev_001",
    run_id: str = "run_ver_01",
    content: str = "Empirical benchmark shows quantum error suppression exceeds 99 percent.",
    trust_level: SourceTrustLevel = SourceTrustLevel.PEER_REVIEWED,
    is_untrusted: bool = False,
    is_quarantined: bool = False,
) -> EvidenceRecord:
    provenance = SourceProvenance.from_content(
        raw_content=content,
        title="Quantum Benchmarks 2026",
        source_url="https://nature.com/articles/quantum-error",
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


def _make_claim(
    claim_id: str = "clm_001",
    run_id: str = "run_ver_01",
    statement: str = "Quantum error suppression exceeds 99 percent.",
    evidence_ids: tuple[str, ...] = ("ev_001",),
    is_untrusted: bool = False,
    is_quarantined: bool = False,
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        run_id=run_id,
        statement=statement,
        supporting_evidence_ids=evidence_ids,
        confidence_score=0.95,
        is_untrusted=is_untrusted,
        is_quarantined=is_quarantined,
    )


def _make_verifier_request(
    request_id: str = "req_ver_001",
    run_id: str = "run_ver_01",
    subtask_id: str = "task_ver_01",
    agent_role: AgentRole = AgentRole.VERIFIER,
    task_type: TaskType = TaskType.VERIFICATION,
    goal_context: str = "Verify quantum computing claims and detect contradictions",
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
        idempotency_key="idem_ver_001",
    )


def test_verifier_worker_protocol_compliance() -> None:
    """Test 1: Verify VerifierWorker implements WorkerProtocol and supports expected task types."""
    worker = VerifierWorker()
    assert isinstance(worker, WorkerProtocol)
    assert TaskType.VERIFICATION in SUPPORTED_VERIFIER_TASK_TYPES
    assert TaskType.CONFLICT_DETECTION in SUPPORTED_VERIFIER_TASK_TYPES


@pytest.mark.asyncio
async def test_conflict_detection_execution() -> None:
    """Test 4: Verify TaskType.CONFLICT_DETECTION evaluates opposing claims and emits ContradictionItems."""
    worker = VerifierWorker()
    claim1 = _make_claim(
        claim_id="clm_pos",
        statement="Superconducting qubits increase gate fidelity and reduce noise.",
    )
    claim2 = _make_claim(
        claim_id="clm_neg",
        statement="Superconducting qubits decrease gate fidelity and increase noise.",
    )

    request = _make_verifier_request(
        task_type=TaskType.CONFLICT_DETECTION,
        input_data={"claims": [claim1.model_dump(), claim2.model_dump()]},
    )

    envelope: WorkerResponseEnvelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.run_id == "run_ver_01"
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["has_contradictions"] is True
    assert output["total_contradictions"] >= 1
    assert len(output["contradictions"]) >= 1

    cnt = output["contradictions"][0]
    assert cnt["run_id"] == "run_ver_01"
    assert "clm_pos" in cnt["conflicting_claim_ids"]
    assert "clm_neg" in cnt["conflicting_claim_ids"]


@pytest.mark.asyncio
async def test_verification_execution_with_citations_and_audits() -> None:
    """Test 5: Verify TaskType.VERIFICATION produces VerificationAudits and normalized CitationReferences."""
    worker = VerifierWorker()
    ev = _make_evidence_record(
        evidence_id="ev_001",
        content="Empirical benchmark shows quantum error suppression exceeds 99 percent.",
    )
    claim = _make_claim(
        claim_id="clm_001",
        evidence_ids=("ev_001",),
    )

    request = _make_verifier_request(
        task_type=TaskType.VERIFICATION,
        input_data={
            "claims": [claim.model_dump()],
            "evidence_records": [ev.model_dump()],
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["verified_count"] == 1
    assert output["unverified_count"] == 0
    assert output["total_audits"] == 1
    assert output["total_citations"] == 1
    assert output["overall_status"] == VerificationStatus.VERIFIED.value

    # Verify Citation Reference
    cit = output["citations"][0]
    assert cit["citation_key"] == "[CIT-01]"
    assert cit["evidence_id"] == "ev_001"
    assert cit["source_url"] == "https://nature.com/articles/quantum-error"

    # Verify Audit Record
    audit = output["audits"][0]
    assert audit["claim_id"] == "clm_001"
    assert audit["status"] == VerificationStatus.VERIFIED.value


@pytest.mark.asyncio
async def test_contradicted_claim_status_mapping() -> None:
    """Test 7: Verify claim with active contradiction receives CONTRADICTED status."""
    worker = VerifierWorker()
    ev1 = _make_evidence_record(evidence_id="ev_01", content="Study A shows increase.")
    ev2 = _make_evidence_record(evidence_id="ev_02", content="Study B shows decrease.")

    claim1 = _make_claim(
        claim_id="c1", statement="Study A shows increase.", evidence_ids=("ev_01",)
    )
    claim2 = _make_claim(
        claim_id="c2", statement="Study B shows decrease.", evidence_ids=("ev_02",)
    )

    contradiction = ContradictionItem(
        item_id="cnt_01",
        run_id="run_ver_01",
        description="Contradiction on increase vs decrease",
        divergence_analysis="Competing assertions regarding directionality",
        conflicting_claim_ids=("c1", "c2"),
        severity_score=1.0,
    )

    request = _make_verifier_request(
        task_type=TaskType.VERIFICATION,
        input_data={
            "claims": [claim1.model_dump(), claim2.model_dump()],
            "evidence_records": [ev1.model_dump(), ev2.model_dump()],
            "contradictions": [contradiction.model_dump()],
        },
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["contradicted_count"] == 2
    assert output["overall_status"] == VerificationStatus.CONTRADICTED.value


@pytest.mark.asyncio
async def test_untrusted_and_quarantined_flag_propagation() -> None:
    """Test 8: Verify is_untrusted and is_quarantined flags propagate to audits and citations."""
    worker = VerifierWorker()
    ev = _make_evidence_record(
        evidence_id="ev_quar_01",
        is_untrusted=True,
        is_quarantined=True,
    )
    claim = _make_claim(
        claim_id="clm_quar_01",
        evidence_ids=("ev_quar_01",),
        is_untrusted=True,
        is_quarantined=True,
    )

    request = _make_verifier_request(
        input_data={
            "claims": [claim.model_dump()],
            "evidence_records": [ev.model_dump()],
        }
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    cit = output["citations"][0]
    assert cit["is_untrusted"] is True
    assert cit["is_quarantined"] is True


@pytest.mark.asyncio
async def test_vector_memory_fallback_retrieval() -> None:
    """Test 9: Verify VectorMemory fallback retrieval when evidence_records are not passed directly."""
    vector_memory = VectorMemory()
    ev = _make_evidence_record(
        evidence_id="ev_mem_01",
        content="Cryogenic electronics enable fast qubit readout below 50 millikelvin.",
    )
    await vector_memory.upsert_evidence([ev])

    worker = VerifierWorker(vector_memory=vector_memory)
    claim = _make_claim(
        claim_id="clm_mem_01",
        statement="Cryogenic electronics enable fast qubit readout below 50 millikelvin.",
        evidence_ids=("ev_mem_01",),
    )

    request = _make_verifier_request(
        goal_context="Cryogenic readout",
        input_data={"claims": [claim.model_dump()], "query": "Cryogenic readout"},
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    output = envelope.response.output_data
    assert output["verified_count"] == 1


@pytest.mark.asyncio
async def test_unsupported_role_rejection() -> None:
    """Test 13: Verify request with unsupported agent role fails with UNSUPPORTED_ROLE."""
    worker = VerifierWorker()
    request = _make_verifier_request(agent_role=AgentRole.RESEARCHER)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_ROLE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_unsupported_task_type_rejection() -> None:
    """Test 14: Verify request with unsupported task type fails with UNSUPPORTED_TASK_TYPE."""
    worker = VerifierWorker()
    request = _make_verifier_request(task_type=TaskType.DECOMPOSITION)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_TASK_TYPE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_empty_run_id_rejection() -> None:
    """Test 11: Verify empty run_id fails with INVALID_RUN_ID."""
    worker = VerifierWorker()
    request = _make_verifier_request(run_id="   ")

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_RUN_ID"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_cross_run_claim_rejection() -> None:
    """Test 12: Verify claim with mismatched run_id is rejected with EVIDENCE_VALIDATION_ERROR."""
    worker = VerifierWorker()
    foreign_claim = _make_claim(
        claim_id="clm_foreign",
        run_id="run_foreign_tenant",
    )

    request = _make_verifier_request(
        run_id="run_ver_01",
        input_data={"claims": [foreign_claim.model_dump()]},
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "EVIDENCE_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_verification_error_mapping() -> None:
    """Test 15: Verify VerificationError maps to VERIFICATION_ERROR with is_retryable=False."""

    class FaultyVerifierAgent(VerifierAgent):
        async def verify_claims(
            self,
            claims: list[ExtractedClaim],
            evidence_pool: list[EvidenceRecord],
            run_id: str,
            contradictions: list[ContradictionItem] | None = None,
        ) -> Any:
            _ = (claims, evidence_pool, run_id, contradictions)
            raise VerificationError("Grounding constraint verification failure")

    worker = VerifierWorker(verifier_agent=FaultyVerifierAgent())
    ev = _make_evidence_record()
    claim = _make_claim()

    request = _make_verifier_request(
        input_data={
            "claims": [claim.model_dump()],
            "evidence_records": [ev.model_dump()],
        }
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "VERIFICATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_deterministic_output_and_identifiers() -> None:
    """Test 16: Verify repeated execution with identical request produces identical deterministic IDs."""
    worker = VerifierWorker()
    ev = _make_evidence_record()
    claim = _make_claim()

    request = _make_verifier_request(
        run_id="run_det_ver",
        input_data={
            "claims": [claim.model_dump()],
            "evidence_records": [ev.model_dump()],
        },
    )

    env1 = await worker.execute(request)
    env2 = await worker.execute(request)

    assert env1.envelope_id == env2.envelope_id
    assert env1.response is not None and env2.response is not None
    assert env1.response.response_id == env2.response.response_id


@pytest.mark.asyncio
async def test_integration_chain_conflict_and_verification() -> None:
    """Test 13 Integration: Verify ExtractedClaim + EvidenceRecord -> VerifierWorker(CONFLICT_DETECTION / VERIFICATION)."""
    detector = ContradictionDetector()
    verifier = VerifierAgent()
    worker = VerifierWorker(verifier_agent=verifier, contradiction_detector=detector)

    ev_a = _make_evidence_record(
        evidence_id="ev_A",
        content="Battery capacity increases at elevated temperatures.",
    )
    ev_b = _make_evidence_record(
        evidence_id="ev_B",
        content="Battery capacity decreases at elevated temperatures.",
    )

    claim_a = _make_claim(
        claim_id="clm_A",
        statement="Battery capacity increases at elevated temperatures.",
        evidence_ids=("ev_A",),
    )
    claim_b = _make_claim(
        claim_id="clm_B",
        statement="Battery capacity decreases at elevated temperatures.",
        evidence_ids=("ev_B",),
    )

    # Phase A: Conflict Detection
    req_conflict = _make_verifier_request(
        task_type=TaskType.CONFLICT_DETECTION,
        input_data={"claims": [claim_a.model_dump(), claim_b.model_dump()]},
    )
    env_conflict = await worker.execute(req_conflict)
    assert env_conflict.status == TaskStatus.COMPLETED
    assert env_conflict.response is not None
    contradictions = env_conflict.response.output_data["contradictions"]
    assert len(contradictions) >= 1

    # Phase B: Verification using detected contradictions
    req_verif = _make_verifier_request(
        task_type=TaskType.VERIFICATION,
        input_data={
            "claims": [claim_a.model_dump(), claim_b.model_dump()],
            "evidence_records": [ev_a.model_dump(), ev_b.model_dump()],
            "contradictions": contradictions,
        },
    )
    env_verif = await worker.execute(req_verif)
    assert env_verif.status == TaskStatus.COMPLETED
    assert env_verif.response is not None
    assert env_verif.response.output_data["contradicted_count"] == 2
    assert len(env_verif.response.output_data["citations"]) == 2

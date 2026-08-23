import pytest
from pydantic import ValidationError

from app.common.enums import RunStage, SourceTrustLevel, VerificationStatus
from app.common.errors import CheckpointCorruptedError
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
    ResearchDossier,
)
from app.orchestration.contracts import TokenUsage
from app.persistence.protocols import RunRecord
from app.state.models import ResearchGoal
from app.state.snapshot import (
    CheckpointSnapshot,
    compute_state_hash,
)


def test_run_record_defaults_and_immutability() -> None:
    """Test 1: Verify RunRecord defaults, immutability, and field validation."""
    goal = ResearchGoal(
        goal_id="goal_test_01",
        query="Investigate multimodal reasoning models",
        domain_tags=("ai", "multimodal"),
        constraints={"max_depth": 3},
        max_subtasks=5,
    )

    record = RunRecord(
        run_id="run_test_01",
        goal=goal,
    )

    assert record.run_id == "run_test_01"
    assert record.status == RunStage.QUEUED
    assert record.version == 1
    assert record.completed_task_ids == ()
    assert record.failed_task_ids == ()
    assert record.cancelled_task_ids == ()
    assert record.is_cancelled is False
    assert record.dossier is None
    assert record.total_token_usage.total_tokens == 0

    # Immutability check
    with pytest.raises(ValidationError):
        record.status = RunStage.RUNNING


def test_run_record_with_updates_version_increment() -> None:
    """Test 2: Verify with_updates produces an updated immutable copy with version bump."""
    goal = ResearchGoal(
        goal_id="goal_test_02",
        query="Analyze protein folding benchmarks",
    )
    record = RunRecord(run_id="run_test_02", goal=goal)

    updated = record.with_updates(
        status=RunStage.RESEARCHING,
        plan_id="plan_02",
        completed_task_ids=["task_01", "task_02"],
        total_token_usage=TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        ),
        duration_seconds=12.5,
    )

    assert record.version == 1
    assert record.status == RunStage.QUEUED

    assert updated.version == 2
    assert updated.status == RunStage.RESEARCHING
    assert updated.plan_id == "plan_02"
    assert updated.completed_task_ids == ("task_01", "task_02")
    assert updated.total_token_usage.total_tokens == 150
    assert updated.duration_seconds == 12.5


def test_run_record_serialization_roundtrip_with_dossier() -> None:
    """Test 3: Verify serialization and deserialization roundtrip with full ResearchDossier."""
    goal = ResearchGoal(
        goal_id="goal_test_03",
        query="Quantum error correction thresholds",
    )
    claim = ExtractedClaim(
        claim_id="claim_01",
        run_id="run_test_03",
        statement="Surface codes have a threshold near 1%.",
        supporting_evidence_ids=("ev_01",),
        confidence_score=0.95,
    )
    citation = CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://arxiv.org/abs/quantum",
        title="Surface Code Thresholds",
        domain="arxiv.org",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )
    finding = KeyFinding(
        finding_id="find_01",
        title="Surface Code Thresholds",
        narrative="Surface codes remain the leading fault-tolerant architecture with ~1% threshold.",
        claim_ids=("claim_01",),
        evidence_ids=("ev_01",),
    )
    evaluation = EvaluationReport(
        report_id="eval_01",
        run_id="run_test_03",
        plan_id="plan_03",
        passed=True,
        overall_score=0.94,
        completeness_score=0.95,
        citation_coverage_score=0.98,
        contradiction_rate=0.0,
        unsupported_claim_rate=0.0,
        source_diversity_score=0.90,
        rubric_scores=(
            EvaluationRubricScore(
                rubric_name="Grounding",
                score=0.98,
                feedback="Excellent citation backing.",
            ),
        ),
        summary_critique="Rigorous and well-supported findings.",
    )
    dossier = ResearchDossier(
        dossier_id="dossier_01",
        run_id="run_test_03",
        goal_query="Quantum error correction thresholds",
        methodology_summary="Decomposed into literature search and verification subtasks.",
        executive_summary="Summary of quantum thresholds.",
        key_findings=(finding,),
        claims=(claim,),
        citations=(citation,),
        confidence_rating=0.95,
        verification_status=VerificationStatus.VERIFIED,
        evaluation=evaluation,
        markdown_report="# Quantum Report\n\nSurface code threshold is ~1%.",
    )

    record = RunRecord(
        run_id="run_test_03",
        goal=goal,
        status=RunStage.COMPLETED,
        dossier=dossier,
        version=5,
    )

    serialized = record.model_dump(mode="json")
    deserialized = RunRecord.model_validate(serialized)

    assert deserialized.run_id == record.run_id
    assert deserialized.status == RunStage.COMPLETED
    assert deserialized.dossier is not None
    assert deserialized.dossier.dossier_id == "dossier_01"
    assert deserialized.dossier.claims[0].statement == claim.statement
    assert deserialized.dossier.citations[0].citation_key == "[CIT-01]"
    assert deserialized.version == 5


def test_checkpoint_integrity_verification() -> None:
    """Test 4: Verify CheckpointSnapshot cryptographically detects payload tampering."""
    payload = {"counter": 42, "stage": "ANALYZING"}
    correct_hash = compute_state_hash(payload)

    valid_snap = CheckpointSnapshot(
        snapshot_id="snap_01",
        run_id="run_test_04",
        stage=RunStage.ANALYZING,
        checkpoint_version=1,
        state_hash=correct_hash,
        state_payload=payload,
    )
    assert valid_snap.verify_integrity() is True
    valid_snap.assert_valid()

    tampered_snap = CheckpointSnapshot(
        snapshot_id="snap_01",
        run_id="run_test_04",
        stage=RunStage.ANALYZING,
        checkpoint_version=1,
        state_hash="tampered_hash_value",
        state_payload=payload,
    )
    assert tampered_snap.verify_integrity() is False
    with pytest.raises(CheckpointCorruptedError):
        tampered_snap.assert_valid()

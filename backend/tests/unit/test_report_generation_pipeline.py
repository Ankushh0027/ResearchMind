"""Unit & Integration tests for the complete Report Generation Pipeline (Phase 7.5)."""

import pytest

from app.adapters.search.base import SearchQuery
from app.adapters.search.mock_search import MockSearchClient
from app.api.service import ResearchService
from app.common.enums import SourceTrustLevel, VerificationStatus
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    EvaluationReport,
    KeyFinding,
    ResearchDossier,
)
from app.intelligence.reporter import ReporterAgent
from app.persistence.in_memory import (
    InMemoryCheckpointRepository,
    InMemoryRunRepository,
)
from app.storage.in_memory import InMemoryArtifactStorage


@pytest.mark.asyncio
async def test_report_generation_from_completed_investigation():
    """Verify that a full investigation correctly compiles into a structured ResearchDossier."""
    agent = ReporterAgent()
    run_id = "run_test_comp_01"
    goal_query = "What is the impact of AI coding assistants on software developer productivity, code quality, and defect rates?"

    finding = KeyFinding(
        finding_id="find_01",
        title="Developer Productivity & Task Completion Speed",
        narrative="Developers using AI coding assistants complete tasks up to 55.8% faster in controlled benchmark studies.",
        claim_ids=("claim_01",),
        evidence_ids=("ev_01",),
        confidence_score=0.95,
        run_id=run_id,
    )

    claim = ExtractedClaim(
        claim_id="claim_01",
        statement="AI assistants reduce task completion time by up to 55.8%.",
        confidence_score=0.95,
        supporting_evidence_ids=("ev_01",),
        run_id=run_id,
    )

    cit = CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://arxiv.org/abs/2302.06590",
        title="The Impact of AI on Developer Productivity",
        domain="arxiv.org",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        run_id=run_id,
    )

    eval_report = EvaluationReport(
        report_id="eval_01",
        run_id=run_id,
        plan_id="plan_01",
        passed=True,
        overall_score=0.96,
        completeness_score=0.95,
        citation_coverage_score=1.0,
        contradiction_rate=0.0,
        unsupported_claim_rate=0.0,
        source_diversity_score=0.92,
        summary_critique="High quality evidence grounding with peer-reviewed validation.",
    )

    dossier: ResearchDossier = await agent.compile_dossier(
        goal_query=goal_query,
        findings=[finding],
        claims=[claim],
        citations=[cit],
        contradictions=[],
        run_id=run_id,
        evaluation=eval_report,
        methodology_summary="Topological DAG execution with arXiv search.",
    )

    assert dossier.dossier_id.startswith("dos_")
    assert dossier.run_id == run_id
    assert dossier.goal_query == goal_query
    assert len(dossier.key_findings) == 1
    assert len(dossier.claims) == 1
    assert len(dossier.citations) == 1
    assert dossier.confidence_rating == 0.96
    assert dossier.verification_status == VerificationStatus.VERIFIED
    assert "Developer Productivity" in dossier.executive_summary
    assert "[CIT-01]" in dossier.markdown_report


@pytest.mark.asyncio
async def test_duplicate_findings_deduplicated_in_report():
    """Verify that multiple identical findings from parallel agent subtasks are deduplicated into a single finding."""
    agent = ReporterAgent()
    run_id = "run_dedup_01"
    goal_query = "What is the impact of AI coding assistants on developer productivity?"

    finding1 = KeyFinding(
        finding_id="find_01",
        title="Developer Productivity & Task Completion",
        narrative="AI assistants reduce task completion time by up to 55.8%.",
        claim_ids=("claim_01",),
        evidence_ids=("ev_01",),
        confidence_score=0.90,
        run_id=run_id,
    )
    finding2 = KeyFinding(
        finding_id="find_02",
        title="Developer Productivity & Task Completion",
        narrative="AI assistants reduce task completion time by up to 55.8%.",
        claim_ids=("claim_02",),
        evidence_ids=("ev_02",),
        confidence_score=0.95,
        run_id=run_id,
    )
    finding3 = KeyFinding(
        finding_id="find_03",
        title="Developer Productivity & Task Completion",
        narrative="AI assistants reduce task completion time by up to 55.8%.",
        claim_ids=("claim_03",),
        evidence_ids=("ev_03",),
        confidence_score=0.92,
        run_id=run_id,
    )

    claim1 = ExtractedClaim(
        claim_id="claim_01",
        statement="AI assistants speed up routine boilerplate by 55.8%.",
        confidence_score=0.95,
        supporting_evidence_ids=("ev_01",),
        run_id=run_id,
    )

    cit1 = CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://arxiv.org/abs/2302.06590",
        title="Productivity RCT",
        domain="arxiv.org",
        run_id=run_id,
    )

    dossier = await agent.compile_dossier(
        goal_query=goal_query,
        findings=[finding1, finding2, finding3],
        claims=[claim1],
        citations=[cit1],
        contradictions=[],
        run_id=run_id,
    )

    # 3 duplicate findings should be deduplicated into 1
    assert len(dossier.key_findings) == 1
    merged = dossier.key_findings[0]
    assert merged.title == "Developer Productivity & Task Completion"
    assert set(merged.claim_ids) == {"claim_01", "claim_02", "claim_03"}
    assert set(merged.evidence_ids) == {"ev_01", "ev_02", "ev_03"}
    assert merged.confidence_score == 0.95


@pytest.mark.asyncio
async def test_mock_search_produces_query_relevant_evidence_without_example_org():
    """Verify that MockSearchClient generates query-relevant scientific search hits and zero example.org leaks."""
    search_client = MockSearchClient()
    query = SearchQuery(
        query="What is the impact of AI coding assistants on software developer productivity, code quality, and defect rates?",
        max_results=5,
    )

    hits = await search_client.search(query)
    assert len(hits) >= 3

    # All hits must be relevant and from real academic domains
    domains = [h.domain for h in hits]
    assert "example.org" not in domains
    assert any("arxiv.org" in d or "acm.org" in d or "ieee.org" in d for d in domains)

    # Content must cover productivity, quality, and defects
    combined_snippets = " ".join(h.snippet.lower() for h in hits)
    assert "productiv" in combined_snippets or "faster" in combined_snippets
    assert "quality" in combined_snippets or "maintainab" in combined_snippets
    assert "defect" in combined_snippets or "security" in combined_snippets


@pytest.mark.asyncio
async def test_report_generation_with_zero_claims():
    """Verify that report generation gracefully handles investigations yielding zero extracted claims."""
    agent = ReporterAgent()
    run_id = "run_zero_claims_01"
    goal_query = "Investigate hypothetical unstudied phenomenon."

    dossier = await agent.compile_dossier(
        goal_query=goal_query,
        findings=[],
        claims=[],
        citations=[],
        contradictions=[],
        run_id=run_id,
        evaluation=None,
    )

    assert dossier.run_id == run_id
    assert len(dossier.claims) == 0
    assert len(dossier.key_findings) == 0
    assert dossier.confidence_rating == 0.0
    assert dossier.verification_status == VerificationStatus.UNVERIFIED
    assert "Evidence is currently insufficient" in dossier.executive_summary
    assert len(dossier.markdown_report) > 0


@pytest.mark.asyncio
async def test_report_generation_with_partially_verified_claims():
    """Verify that partially verified claims produce PARTIALLY_VERIFIED status when citations are insufficient."""
    agent = ReporterAgent()
    run_id = "run_partial_01"
    goal_query = "Impact of quantum annealing on NP-hard optimization."

    finding1 = KeyFinding(
        finding_id="f_01",
        title="Theoretical Speedup Claim",
        narrative="Some speedups observed in Ising spin glasses.",
        confidence_score=0.75,
        run_id=run_id,
    )
    finding2 = KeyFinding(
        finding_id="f_02",
        title="Hardware Noise Bottlenecks",
        narrative="Thermal fluctuations limit coherence times.",
        confidence_score=0.70,
        run_id=run_id,
    )

    claim = ExtractedClaim(
        claim_id="cl_01",
        statement="Coherence times limit large-scale scaling.",
        confidence_score=0.70,
        supporting_evidence_ids=("ev_01",),
        run_id=run_id,
    )

    cit = CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://arxiv.org/abs/2307.12008",
        title="Quantum Annealing Overview",
        domain="arxiv.org",
        run_id=run_id,
    )

    dossier = await agent.compile_dossier(
        goal_query=goal_query,
        findings=[finding1, finding2],
        claims=[claim],
        citations=[cit],
        contradictions=[],
        run_id=run_id,
    )

    assert dossier.verification_status == VerificationStatus.PARTIALLY_VERIFIED
    assert dossier.confidence_rating == pytest.approx(0.725, rel=1e-2)


@pytest.mark.asyncio
async def test_unsupported_claims_not_marked_as_verified():
    """Verify that unsupported/unverified claims maintain accurate unverified status."""
    agent = ReporterAgent()
    run_id = "run_unsupported_01"
    goal_query = "Unverified claim safety audit."

    unsupported_claim = ExtractedClaim(
        claim_id="claim_unsupported",
        statement="Unverified assertion without empirical backing.",
        confidence_score=0.2,
        supporting_evidence_ids=("ev_unverified",),
        contradiction_notes="Conflicting evidence exists",
        run_id=run_id,
    )

    dossier = await agent.compile_dossier(
        goal_query=goal_query,
        findings=[],
        claims=[unsupported_claim],
        citations=[],
        contradictions=[],
        run_id=run_id,
    )

    assert dossier.claims[0].confidence_score == 0.2
    assert dossier.claims[0].contradiction_notes == "Conflicting evidence exists"
    assert dossier.verification_status == VerificationStatus.UNVERIFIED


@pytest.mark.asyncio
async def test_api_service_get_report_response():
    """Verify that ResearchService.get_report returns a properly populated ResearchReportResponse."""
    run_repo = InMemoryRunRepository()
    ckpt_repo = InMemoryCheckpointRepository()
    storage = InMemoryArtifactStorage()

    service = ResearchService(
        run_repo=run_repo,
        checkpoint_repo=ckpt_repo,
        artifact_storage=storage,
    )

    none_rep = await service.get_report("run_non_existent")
    assert none_rep is None

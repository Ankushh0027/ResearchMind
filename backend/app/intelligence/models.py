"""Intelligence output schemas, EvaluationReport, and ResearchDossier contracts."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import SourceTrustLevel, VerificationStatus
from app.common.evidence import ExtractedClaim


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CitationReference(BaseModel):
    """Normalized citation linking a finding or claim back to raw source provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_key: str = Field(
        ..., min_length=1, description="Short inline key (e.g. [CIT-01])"
    )
    evidence_id: str = Field(
        ..., min_length=1, description="Referenced EvidenceRecord ID"
    )
    source_url: str = Field(
        ..., min_length=1, description="Source URL or document identifier"
    )
    title: str = Field(
        ..., min_length=1, description="Source document or article title"
    )
    domain: str = Field(..., description="Source host domain")
    publication_date: str | None = Field(
        default=None, description="ISO publication date if available"
    )
    trust_level: SourceTrustLevel = Field(
        default=SourceTrustLevel.GENERAL_WEB, description="Source trust category"
    )
    run_id: str | None = Field(
        default=None, description="Associated research run ID for tenant isolation"
    )
    is_untrusted: bool = Field(
        default=False,
        description="Flag indicating if the cited source required boundary sanitization",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Flag indicating if the cited source contained quarantined content",
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Creation timestamp"
    )


class KeyFinding(BaseModel):
    """Synthesized core research insight supported by extracted factual claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(..., min_length=1, description="Unique finding identifier")
    title: str = Field(..., min_length=1, description="Concise finding headline")
    narrative: str = Field(
        ..., min_length=1, description="Synthesized analytical narrative"
    )
    claim_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of claims supporting this finding"
    )
    evidence_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="IDs of direct evidence supporting this finding",
    )
    run_id: str | None = Field(
        default=None, description="Associated research run ID for tenant isolation"
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Grounded confidence rating [0.0 - 1.0]",
    )
    is_untrusted: bool = Field(
        default=False,
        description="Flag indicating if any supporting claim derives from untrusted evidence",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Flag indicating if any supporting claim derives from quarantined evidence",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Contextual analytical metadata"
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Creation timestamp"
    )


class ContradictionItem(BaseModel):
    """Documented factual disagreement or divergence between competing claims/sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(
        ..., min_length=1, description="Unique contradiction identifier"
    )
    description: str = Field(
        ..., min_length=1, description="Summary of the contradiction"
    )
    conflicting_claim_ids: tuple[str, ...] = Field(
        ..., min_length=2, description="IDs of contradictory claims"
    )
    divergence_analysis: str = Field(
        ..., min_length=1, description="Analysis of why sources disagree"
    )
    run_id: str | None = Field(
        default=None, description="Associated research run ID for tenant isolation"
    )
    conflicting_evidence_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="IDs of evidence records underlying the contradictory claims",
    )
    severity_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Severity or confidence of the contradiction [0.0 - 1.0]",
    )
    is_untrusted: bool = Field(
        default=False,
        description="Flag indicating if any conflicting claim originates from untrusted sources",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Flag indicating if any conflicting claim originates from quarantined sources",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Contextual contradiction metadata"
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Creation timestamp"
    )


class EvaluationRubricScore(BaseModel):
    """Evaluation score for a specific quality dimension."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rubric_name: str = Field(..., min_length=1, description="Quality dimension name")
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized score [0.0 - 1.0]"
    )
    weight: float = Field(
        default=1.0, gt=0.0, description="Weighting factor in overall calculation"
    )
    feedback: str = Field(
        ..., min_length=1, description="Detailed critique and suggestions"
    )


class EvaluationReport(BaseModel):
    """Formal self-evaluation quality audit evaluating research rigor and coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str = Field(
        ..., min_length=1, description="Unique evaluation report identifier"
    )
    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    plan_id: str = Field(..., min_length=1, description="Associated research plan ID")
    passed: bool = Field(
        ..., description="Whether the research meets acceptance thresholds"
    )
    overall_score: float = Field(
        ..., ge=0.0, le=1.0, description="Composite quality rating [0.0 - 1.0]"
    )
    completeness_score: float = Field(
        ..., ge=0.0, le=1.0, description="Goal inquiry coverage score"
    )
    citation_coverage_score: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio of factual claims backed by citations"
    )
    contradiction_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Proportion of unresolved contradictions"
    )
    unsupported_claim_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Proportion of ungrounded assertions"
    )
    source_diversity_score: float = Field(
        ..., ge=0.0, le=1.0, description="Diversity metric across domains/authors"
    )
    rubric_scores: tuple[EvaluationRubricScore, ...] = Field(
        default_factory=tuple, description="Granular rubric assessments"
    )
    summary_critique: str = Field(
        ..., min_length=1, description="Overall evaluator critique"
    )
    created_at: datetime = Field(default_factory=_utc_now)


class ResearchDossier(BaseModel):
    """Final, publication-ready research dossier compiling synthesized findings with full provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dossier_id: str = Field(
        ..., min_length=1, description="Unique research dossier identifier"
    )
    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    goal_query: str = Field(
        ..., min_length=1, description="Original user research goal or question"
    )
    methodology_summary: str = Field(
        ...,
        min_length=1,
        description="Summary of subtask search decomposition strategy",
    )
    executive_summary: str = Field(
        ..., min_length=1, description="Executive summary of findings"
    )
    key_findings: tuple[KeyFinding, ...] = Field(
        default_factory=tuple, description="Thematic synthesized findings"
    )
    claims: tuple[ExtractedClaim, ...] = Field(
        default_factory=tuple, description="Extracted factual claims"
    )
    citations: tuple[CitationReference, ...] = Field(
        default_factory=tuple, description="Comprehensive citation index"
    )
    contradictions: tuple[ContradictionItem, ...] = Field(
        default_factory=tuple, description="Documented contradictory perspectives"
    )
    limitations: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Acknowledged data gaps or inquiry limitations",
    )
    confidence_rating: float = Field(
        ..., ge=0.0, le=1.0, description="Overall research confidence score [0.0 - 1.0]"
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.VERIFIED, description="Aggregate verification status"
    )
    evaluation: EvaluationReport | None = Field(
        default=None, description="Attached self-evaluation report"
    )
    markdown_report: str = Field(
        ...,
        min_length=1,
        description="Publication-ready formatted Markdown deliverable",
    )
    created_at: datetime = Field(default_factory=_utc_now)

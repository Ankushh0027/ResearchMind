"""Evidence, provenance, and claim verification models."""

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.enums import SourceTrustLevel, VerificationStatus


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SourceProvenance(BaseModel):
    """Provenance metadata tracking the origin and credibility of external content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_url: str = Field(..., description="Canonical source URL or document URI")
    title: str = Field(..., min_length=1, description="Document or page title")
    authors: tuple[str, ...] = Field(
        default_factory=tuple, description="Identified authors or issuing entities"
    )
    domain: str = Field(..., description="Root domain or publishing platform")
    trust_level: SourceTrustLevel = Field(
        default=SourceTrustLevel.GENERAL_WEB,
        description="Assessed trust tier of the source",
    )
    publication_date: str | None = Field(
        default=None, description="ISO formatted publication date if extracted"
    )
    content_hash: str = Field(
        ..., description="Cryptographic SHA-256 hash of raw source content"
    )
    ingested_at: datetime = Field(
        default_factory=_utc_now, description="Timestamp of raw document ingestion"
    )

    @classmethod
    def compute_content_hash(cls, raw_content: str | bytes) -> str:
        """Compute deterministic SHA-256 hash of content."""
        if isinstance(raw_content, str):
            raw_content = raw_content.encode("utf-8")
        return hashlib.sha256(raw_content).hexdigest()


class EvidenceRecord(BaseModel):
    """Atomic factual evidence extracted from a verified primary source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(
        ..., min_length=1, description="Unique evidence identifier"
    )
    run_id: str = Field(..., min_length=1, description="Research run identifier")
    subtask_id: str = Field(
        ..., min_length=1, description="Inquiry subtask that collected this evidence"
    )
    provenance: SourceProvenance = Field(
        ..., description="Provenance information of the source document"
    )
    extracted_quote: str = Field(
        ..., min_length=1, description="Direct verbatim or extracted textual evidence"
    )
    context_summary: str = Field(
        ..., description="Surrounding contextual summary explaining relevance"
    )
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0, description="Estimated relevance score [0.0 - 1.0]"
    )
    vector_point_id: str | None = Field(
        default=None, description="Qdrant point ID if indexed into vector memory"
    )
    is_untrusted: bool = Field(
        default=False,
        description="Flag indicating whether the source text requires sanitization",
    )
    created_at: datetime = Field(default_factory=_utc_now)


class ExtractedClaim(BaseModel):
    """Factual assertion synthesized by an Analyst agent with source traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(..., min_length=1, description="Unique claim identifier")
    run_id: str = Field(..., min_length=1, description="Research run identifier")
    statement: str = Field(
        ..., min_length=1, description="Declarative factual claim statement"
    )
    supporting_evidence_ids: tuple[str, ...] = Field(
        ..., min_length=1, description="Immutable tuple of supporting evidence IDs"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Analyst confidence rating [0.0 - 1.0]"
    )
    contradiction_notes: str | None = Field(
        default=None,
        description="Notes on competing claims or inconsistencies detected",
    )
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("supporting_evidence_ids")
    @classmethod
    def validate_non_empty_evidence(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError(
                "An extracted claim must reference at least one supporting evidence record"
            )
        return v


class VerificationAudit(BaseModel):
    """Formal audit record of claim cross-examination and grounding verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(
        ..., min_length=1, description="Unique audit record identifier"
    )
    claim_id: str = Field(
        ..., min_length=1, description="ID of claim under verification"
    )
    run_id: str = Field(..., min_length=1, description="Research run identifier")
    status: VerificationStatus = Field(
        ..., description="Final verification outcome status"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Verifier certainty score [0.0 - 1.0]"
    )
    verified_evidence_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Evidence IDs directly confirming this claim",
    )
    refuting_evidence_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Evidence IDs directly contradicting this claim",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Explanatory rationale for the verification verdict",
    )
    auditor_agent_role: str = Field(
        default="verifier", description="Agent role that performed this verification"
    )
    verified_at: datetime = Field(default_factory=_utc_now)

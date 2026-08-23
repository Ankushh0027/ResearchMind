"""Claim extraction domain models, grounded factual assertion contracts, and deterministic extractor.

Defines immutable ExtractedClaim structures, extraction result envelopes, and a hermetic,
grounded claim extraction engine that extracts factual assertions strictly bound to verified
EvidenceRecord identifiers with zero hallucination.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.enums import SourceTrustLevel
from app.common.errors import (
    EvidenceValidationError,
    UngroundedClaimError,
)
from app.intelligence.evidence import EvidenceRecord

TRUST_LEVEL_BASE_CONFIDENCE: dict[SourceTrustLevel, float] = {
    SourceTrustLevel.PEER_REVIEWED: 0.95,
    SourceTrustLevel.OFFICIAL_DOC: 0.90,
    SourceTrustLevel.TRUSTED_PRIMARY: 0.90,
    SourceTrustLevel.GENERAL_WEB: 0.70,
    SourceTrustLevel.UNVERIFIED_USER_UPLOAD: 0.40,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def generate_claim_id(prefix: str = "clm") -> str:
    """Generate a unique identifier for an extracted factual claim."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ExtractedClaim(BaseModel):
    """Factual assertion extracted from empirical evidence with mandatory source traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(
        default_factory=generate_claim_id,
        min_length=1,
        description="Unique claim identifier",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="Associated research run ID for tenant isolation",
    )
    statement: str = Field(
        ...,
        min_length=1,
        description="Declarative factual proposition statement",
    )
    supporting_evidence_ids: tuple[str, ...] = Field(
        ...,
        min_length=1,
        description="Immutable tuple of supporting EvidenceRecord IDs (non-empty)",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Grounded confidence rating [0.0 - 1.0]",
    )
    topic_tags: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Thematic category or domain tags",
    )
    is_untrusted: bool = Field(
        default=False,
        description="Inherited flag indicating source required boundary sanitization",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Inherited flag indicating hostile injection patterns were detected",
    )
    contradiction_notes: str | None = Field(
        default=None,
        description="Notes on competing claims or inconsistencies detected",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual metadata propagated from evidence",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Creation timestamp",
    )

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("run_id must not be empty or whitespace only")
        return v.strip()

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("statement must not be empty or whitespace only")
        return v.strip()

    @field_validator("supporting_evidence_ids")
    @classmethod
    def validate_supporting_evidence_ids(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError(
                "supporting_evidence_ids must contain at least one valid evidence ID"
            )
        clean_ids: list[str] = []
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "Each evidence ID in supporting_evidence_ids must be a non-empty string"
                )
            clean_ids.append(item.strip())
        return tuple(clean_ids)


class ClaimExtractionResult(BaseModel):
    """Result envelope containing extracted claims and analyzed evidence provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    claims: tuple[ExtractedClaim, ...] = Field(
        default_factory=tuple, description="Immutable tuple of extracted claims"
    )
    evidence_ids_analyzed: tuple[str, ...] = Field(
        default_factory=tuple,
        description="All EvidenceRecord IDs processed during extraction",
    )
    total_claims: int = Field(..., ge=0, description="Total count of claims extracted")


@runtime_checkable
class ClaimExtractorProtocol(Protocol):
    """Protocol for factual claim extraction from evidence collections."""

    async def extract_claims(
        self, evidence_records: list[EvidenceRecord], run_id: str
    ) -> ClaimExtractionResult:
        """Extract grounded factual claims from evidence records."""
        ...


class DeterministicClaimExtractor(ClaimExtractorProtocol):
    """Rule-based, offline, deterministic claim extractor extracting grounded propositions."""

    def __init__(
        self,
        min_sentence_length: int = 15,
        max_claims_per_evidence: int = 20,
    ) -> None:
        if min_sentence_length <= 0:
            raise EvidenceValidationError(
                f"min_sentence_length must be positive, got {min_sentence_length}"
            )
        if max_claims_per_evidence <= 0:
            raise EvidenceValidationError(
                f"max_claims_per_evidence must be positive, got {max_claims_per_evidence}"
            )
        self.min_sentence_length = min_sentence_length
        self.max_claims_per_evidence = max_claims_per_evidence
        # Sentence splitting pattern (periods, question marks, exclamation marks, or newlines)
        self._sentence_regex = re.compile(r"(?<=[.!?\n])\s+")

    def _split_into_propositions(self, text: str) -> list[str]:
        raw_parts = self._sentence_regex.split(text.strip())
        propositions: list[str] = []
        for part in raw_parts:
            clean = part.strip()
            # Remove trailing periods / punct for normalization
            clean = re.sub(r"^[-*•\s]+", "", clean)
            if len(clean) >= self.min_sentence_length:
                propositions.append(clean)
        return propositions

    def _calculate_confidence(self, record: EvidenceRecord) -> float:
        base = TRUST_LEVEL_BASE_CONFIDENCE.get(record.provenance.trust_level, 0.70)
        if record.is_quarantined:
            base -= 0.20
        elif record.is_untrusted:
            base -= 0.05
        return max(0.1, min(1.0, round(base, 3)))

    async def extract_claims(
        self, evidence_records: list[EvidenceRecord], run_id: str
    ) -> ClaimExtractionResult:
        """Extract grounded factual claims from a list of EvidenceRecords with strict run isolation."""
        if evidence_records is None or not isinstance(evidence_records, list):
            raise TypeError(
                "evidence_records must be a list of EvidenceRecord instances"
            )

        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty or whitespace only")
        clean_run_id = run_id.strip()

        extracted_claims: list[ExtractedClaim] = []
        analyzed_ids: list[str] = []
        seen_statements: set[str] = set()

        for record in evidence_records:
            if not isinstance(record, EvidenceRecord):
                raise TypeError(f"Expected EvidenceRecord, got {type(record).__name__}")

            # Strict run isolation check
            if record.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Evidence record '{record.evidence_id}' has run_id '{record.run_id}' "
                    f"which does not match extraction run_id '{clean_run_id}'"
                )

            if record.evidence_id not in analyzed_ids:
                analyzed_ids.append(record.evidence_id)

            propositions = self._split_into_propositions(record.normalized_content)
            confidence = self._calculate_confidence(record)

            claim_count_for_record = 0
            for prop in propositions:
                if prop in seen_statements:
                    continue
                seen_statements.add(prop)

                # Ensure non-empty evidence backlinks (satisfies grounding requirement)
                if not record.evidence_id:
                    raise UngroundedClaimError(
                        claim_statement=prop,
                        reason="Evidence record ID is missing or empty",
                    )

                meta = {
                    "source_title": record.provenance.title,
                    "source_domain": record.provenance.domain,
                    "source_url": record.provenance.source_url,
                }

                claim = ExtractedClaim(
                    claim_id=generate_claim_id(),
                    run_id=clean_run_id,
                    statement=prop,
                    supporting_evidence_ids=(record.evidence_id,),
                    confidence_score=confidence,
                    is_untrusted=record.is_untrusted,
                    is_quarantined=record.is_quarantined,
                    metadata=meta,
                )
                extracted_claims.append(claim)
                claim_count_for_record += 1
                if claim_count_for_record >= self.max_claims_per_evidence:
                    break

        return ClaimExtractionResult(
            run_id=clean_run_id,
            claims=tuple(extracted_claims),
            evidence_ids_analyzed=tuple(analyzed_ids),
            total_claims=len(extracted_claims),
        )


__all__ = [
    "ClaimExtractionResult",
    "ClaimExtractorProtocol",
    "DeterministicClaimExtractor",
    "ExtractedClaim",
    "TRUST_LEVEL_BASE_CONFIDENCE",
    "generate_claim_id",
]

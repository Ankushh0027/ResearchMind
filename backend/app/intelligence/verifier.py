"""Verifier agent, claim-to-evidence grounding audits, and citation mapping.

Cross-examines extracted claims against the primary evidence pool, detects ungrounded assertions,
resolves contradiction status, and generates deterministic, publication-grade citation references
with strict multi-tenant run isolation.
"""

import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import VerificationStatus
from app.common.errors import (
    EvidenceValidationError,
    UngroundedCitationError,
)
from app.common.evidence import VerificationAudit
from app.intelligence.claims import ExtractedClaim
from app.intelligence.evidence import EvidenceRecord
from app.intelligence.models import CitationReference, ContradictionItem


def generate_audit_id(prefix: str = "aud") -> str:
    """Generate a unique audit identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _deterministic_audit_id(run_id: str, claim_id: str) -> str:
    """Generate a deterministic UUID-based audit ID from run_id and claim_id."""
    token = f"{run_id}:{claim_id}"
    return f"aud_{uuid.uuid5(uuid.NAMESPACE_DNS, token).hex[:16]}"


def generate_citation_key(index: int) -> str:
    """Format a standard citation reference key [CIT-XX]."""
    return f"[CIT-{index:02d}]"


class VerificationResult(BaseModel):
    """Result envelope for claim verification and citation mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    audits: tuple[VerificationAudit, ...] = Field(
        default_factory=tuple,
        description="Immutable tuple of claim verification audits",
    )
    citations: tuple[CitationReference, ...] = Field(
        default_factory=tuple,
        description="Immutable tuple of normalized source citation references",
    )
    claim_to_citation_map: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Mapping from claim_id to tuple of assigned citation keys",
    )
    overall_status: VerificationStatus = Field(
        ..., description="Aggregate verification status"
    )
    verified_count: int = Field(..., ge=0, description="Total verified claim count")
    unverified_count: int = Field(..., ge=0, description="Total unverified claim count")
    contradicted_count: int = Field(
        ..., ge=0, description="Total contradicted claim count"
    )
    average_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Mean verification confidence score"
    )


@runtime_checkable
class VerifierProtocol(Protocol):
    """Protocol for verifying claims against primary evidence collections."""

    async def verify_claims(
        self,
        claims: list[ExtractedClaim],
        evidence_pool: list[EvidenceRecord],
        run_id: str,
        contradictions: list[ContradictionItem] | None = None,
    ) -> VerificationResult:
        """Cross-examine claims and produce grounding verification audits."""
        ...


class VerifierAgent(VerifierProtocol):
    """Deterministic verifier agent performing rigorous grounding checks and citation mapping."""

    def __init__(self, strict_grounding: bool = True) -> None:
        self.strict_grounding = strict_grounding

    async def verify_claims(
        self,
        claims: list[ExtractedClaim],
        evidence_pool: list[EvidenceRecord],
        run_id: str,
        contradictions: list[ContradictionItem] | None = None,
    ) -> VerificationResult:
        """Verify claims against evidence pool with strict multi-tenant run isolation."""
        if claims is None or not isinstance(claims, list):
            raise TypeError("claims must be a list of ExtractedClaim instances")

        if evidence_pool is None or not isinstance(evidence_pool, list):
            raise TypeError("evidence_pool must be a list of EvidenceRecord instances")

        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty or whitespace only")
        clean_run_id = run_id.strip()

        # Enforce strict run isolation on claims
        for c in claims:
            if not isinstance(c, ExtractedClaim):
                raise TypeError(f"Expected ExtractedClaim, got {type(c).__name__}")
            if c.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Claim '{c.claim_id}' has run_id '{c.run_id}' "
                    f"which does not match verification run_id '{clean_run_id}'"
                )

        # Enforce strict run isolation on evidence records
        evidence_map: dict[str, EvidenceRecord] = {}
        for ev in evidence_pool:
            if not isinstance(ev, EvidenceRecord):
                raise TypeError(f"Expected EvidenceRecord, got {type(ev).__name__}")
            if ev.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Evidence '{ev.evidence_id}' has run_id '{ev.run_id}' "
                    f"which does not match verification run_id '{clean_run_id}'"
                )
            evidence_map[ev.evidence_id] = ev

        # Handle empty claims gracefully
        if not claims:
            return VerificationResult(
                run_id=clean_run_id,
                audits=(),
                citations=(),
                claim_to_citation_map={},
                overall_status=VerificationStatus.UNVERIFIED,
                verified_count=0,
                unverified_count=0,
                contradicted_count=0,
                average_confidence=0.0,
            )

        # Build contradiction lookup
        refuting_evidence_by_claim: dict[str, set[str]] = {}
        if contradictions:
            for cnt in contradictions:
                if not isinstance(cnt, ContradictionItem):
                    raise TypeError(
                        f"Expected ContradictionItem, got {type(cnt).__name__}"
                    )
                if cnt.run_id and cnt.run_id != clean_run_id:
                    raise EvidenceValidationError(
                        f"Contradiction item '{cnt.item_id}' has run_id '{cnt.run_id}' "
                        f"which does not match verification run_id '{clean_run_id}'"
                    )
                for cid in cnt.conflicting_claim_ids:
                    if cid not in refuting_evidence_by_claim:
                        refuting_evidence_by_claim[cid] = set()
                    refuting_evidence_by_claim[cid].update(cnt.conflicting_evidence_ids)

        audits: list[VerificationAudit] = []
        verified_evidence_ids_set: set[str] = set()

        for claim in claims:
            missing_ids = [
                ev_id
                for ev_id in claim.supporting_evidence_ids
                if ev_id not in evidence_map
            ]

            if missing_ids:
                if self.strict_grounding:
                    status = VerificationStatus.UNVERIFIED
                    reasoning = (
                        f"Claim fails grounding: supporting evidence IDs {missing_ids} "
                        f"were not found in the verified evidence pool."
                    )
                    confidence = 0.0
                    verified_ev: tuple[str, ...] = ()
                    refuting_ev: tuple[str, ...] = ()
                else:
                    status = VerificationStatus.INSUFFICIENT_EVIDENCE
                    reasoning = f"Partial evidence found; missing IDs: {missing_ids}."
                    confidence = round(claim.confidence_score * 0.3, 3)
                    verified_ev = tuple(
                        ev_id
                        for ev_id in claim.supporting_evidence_ids
                        if ev_id in evidence_map
                    )
                    refuting_ev = ()
            elif claim.claim_id in refuting_evidence_by_claim:
                status = VerificationStatus.CONTRADICTED
                refuting_ev = tuple(sorted(refuting_evidence_by_claim[claim.claim_id]))
                verified_ev = tuple(claim.supporting_evidence_ids)
                reasoning = (
                    f"Claim is directly disputed by conflicting evidence records: "
                    f"{', '.join(refuting_ev)}."
                )
                confidence = round(claim.confidence_score * 0.5, 3)
                verified_evidence_ids_set.update(verified_ev)
            else:
                status = VerificationStatus.VERIFIED
                verified_ev = tuple(claim.supporting_evidence_ids)
                refuting_ev = ()
                reasoning = (
                    f"Claim is fully grounded in verified evidence: "
                    f"{', '.join(verified_ev)} without unresolved contradictions."
                )
                # Apply minor discount if untrusted source
                confidence = round(
                    claim.confidence_score * (0.90 if claim.is_untrusted else 1.0),
                    3,
                )
                verified_evidence_ids_set.update(verified_ev)

            audit_id = _deterministic_audit_id(clean_run_id, claim.claim_id)
            audit = VerificationAudit(
                audit_id=audit_id,
                claim_id=claim.claim_id,
                run_id=clean_run_id,
                status=status,
                confidence_score=confidence,
                verified_evidence_ids=verified_ev,
                refuting_evidence_ids=refuting_ev,
                reasoning=reasoning,
                auditor_agent_role="verifier",
            )
            audits.append(audit)

        # Build citations for verified evidence records
        sorted_ev_ids = sorted(verified_evidence_ids_set)
        citation_map: dict[str, str] = {}
        citations_list: list[CitationReference] = []

        for idx, ev_id in enumerate(sorted_ev_ids, start=1):
            if ev_id not in evidence_map:
                raise UngroundedCitationError(evidence_id=ev_id)

            ev_record = evidence_map[ev_id]
            cit_key = generate_citation_key(idx)
            citation_map[ev_id] = cit_key

            pub_date = (
                str(ev_record.provenance.metadata.get("publication_date"))
                if (
                    ev_record.provenance.metadata
                    and ev_record.provenance.metadata.get("publication_date")
                )
                else None
            )

            cit_ref = CitationReference(
                citation_key=cit_key,
                evidence_id=ev_id,
                source_url=ev_record.provenance.source_url or "https://unknown.source",
                title=ev_record.provenance.title,
                domain=ev_record.provenance.domain,
                publication_date=pub_date,
                trust_level=ev_record.provenance.trust_level,
                run_id=clean_run_id,
                is_untrusted=ev_record.is_untrusted,
                is_quarantined=ev_record.is_quarantined,
            )
            citations_list.append(cit_ref)

        # Build claim to citation keys mapping
        claim_to_cit_keys: dict[str, tuple[str, ...]] = {}
        for claim in claims:
            keys: list[str] = []
            for ev_id in claim.supporting_evidence_ids:
                if ev_id in citation_map:
                    keys.append(citation_map[ev_id])
            claim_to_cit_keys[claim.claim_id] = tuple(sorted(set(keys)))

        # Aggregate statistics
        verified_cnt = sum(1 for a in audits if a.status == VerificationStatus.VERIFIED)
        unverified_cnt = sum(
            1
            for a in audits
            if a.status
            in (VerificationStatus.UNVERIFIED, VerificationStatus.INSUFFICIENT_EVIDENCE)
        )
        contradicted_cnt = sum(
            1 for a in audits if a.status == VerificationStatus.CONTRADICTED
        )

        avg_conf = (
            round(sum(a.confidence_score for a in audits) / len(audits), 3)
            if audits
            else 0.0
        )

        if verified_cnt == len(claims) and len(claims) > 0:
            overall_status = VerificationStatus.VERIFIED
        elif contradicted_cnt > 0:
            overall_status = VerificationStatus.CONTRADICTED
        elif verified_cnt > 0:
            overall_status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            overall_status = VerificationStatus.UNVERIFIED

        return VerificationResult(
            run_id=clean_run_id,
            audits=tuple(audits),
            citations=tuple(citations_list),
            claim_to_citation_map=claim_to_cit_keys,
            overall_status=overall_status,
            verified_count=verified_cnt,
            unverified_count=unverified_cnt,
            contradicted_count=contradicted_cnt,
            average_confidence=avg_conf,
        )


__all__ = [
    "VerificationResult",
    "VerifierAgent",
    "VerifierProtocol",
    "generate_audit_id",
    "generate_citation_key",
]

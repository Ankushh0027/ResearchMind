"""Contradiction and factual divergence detection layer.

Consumes grounded ExtractedClaim instances, evaluates cross-source pairwise propositions,
and identifies factual disagreements, diametric assertions, and polar divergences with
strict run_id isolation, full provenance preservation, and deterministic ordering.
"""

import re
import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.common.errors import (
    ContradictionDetectionError,
    EvidenceValidationError,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import ContradictionItem

# Antonym and opposing polarity pairs
OPPOSING_POLARITY_PAIRS: list[tuple[set[str], set[str]]] = [
    (
        {
            "increase",
            "increases",
            "increased",
            "increasing",
            "higher",
            "grows",
            "growth",
            "surpasses",
            "exceeds",
        },
        {
            "decrease",
            "decreases",
            "decreased",
            "decreasing",
            "reduces",
            "reduced",
            "reducing",
            "lower",
            "drops",
            "falls",
        },
    ),
    (
        {
            "improves",
            "improved",
            "improving",
            "enhances",
            "enhanced",
            "accelerates",
            "boosts",
        },
        {
            "degrades",
            "degraded",
            "degrading",
            "worsens",
            "worsened",
            "worsening",
            "slows",
            "impedes",
        },
    ),
    (
        {
            "effective",
            "efficient",
            "feasible",
            "viable",
            "beneficial",
            "optimal",
            "scalable",
        },
        {
            "ineffective",
            "inefficient",
            "infeasible",
            "unviable",
            "detrimental",
            "suboptimal",
            "unscalable",
        },
    ),
    (
        {"safe", "harmless", "non-toxic", "benign", "secure"},
        {"hazardous", "dangerous", "toxic", "harmful", "unsafe", "insecure"},
    ),
    (
        {"outperforms", "outperformed", "superior", "exceeds"},
        {"underperforms", "underperformed", "inferior", "lags"},
    ),
    (
        {
            "confirms",
            "confirmed",
            "verifies",
            "verified",
            "supports",
            "supported",
            "proves",
        },
        {
            "refutes",
            "refuted",
            "disproves",
            "disproved",
            "contradicts",
            "contradicted",
            "rejects",
        },
    ),
    (
        {"capable", "enables", "allows", "supports", "permits"},
        {"incapable", "fails", "cannot", "prevents", "prohibits", "lacks"},
    ),
    (
        {"positive", "favorable", "advantageous"},
        {"negative", "unfavorable", "disadvantageous"},
    ),
]

NEGATION_TOKENS = {"not", "no", "never", "neither", "none", "cannot", "fails"}
STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "by",
    "of",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
}


def generate_contradiction_id(prefix: str = "cnt") -> str:
    """Generate a unique identifier for a detected contradiction."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _deterministic_item_id(run_id: str, claim_id_1: str, claim_id_2: str) -> str:
    """Generate a deterministic UUID-based contradiction item ID from sorted claim IDs."""
    c1, c2 = min(claim_id_1, claim_id_2), max(claim_id_1, claim_id_2)
    token = f"{run_id}:{c1}:{c2}"
    return f"cnt_{uuid.uuid5(uuid.NAMESPACE_DNS, token).hex[:16]}"


class ContradictionDetectionResult(BaseModel):
    """Result envelope containing detected contradictions across claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    contradictions: tuple[ContradictionItem, ...] = Field(
        default_factory=tuple,
        description="Immutable tuple of detected contradiction items",
    )
    claims_evaluated: int = Field(
        ..., ge=0, description="Total count of claims evaluated"
    )
    total_contradictions: int = Field(
        ..., ge=0, description="Total count of contradictions found"
    )
    has_contradictions: bool = Field(
        default=False, description="Whether any contradictions were detected"
    )


@runtime_checkable
class ContradictionDetectorProtocol(Protocol):
    """Protocol for detecting factual contradictions and divergent perspectives."""

    async def detect_contradictions(
        self,
        claims: list[ExtractedClaim],
        run_id: str,
    ) -> ContradictionDetectionResult:
        """Analyze a collection of claims to detect factual disagreements."""
        ...


class ContradictionDetector(ContradictionDetectorProtocol):
    """Deterministic, rule-based offline contradiction detector."""

    def __init__(self, min_word_overlap: int = 2) -> None:
        if min_word_overlap <= 0:
            raise EvidenceValidationError(
                f"min_word_overlap must be a positive integer, got {min_word_overlap}"
            )
        self.min_word_overlap = min_word_overlap

    def _tokenize(self, text: str) -> set[str]:
        words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
        return {w for w in words if w not in STOP_WORDS and len(w) > 1}

    def _detect_polarity_clash(
        self, tokens1: set[str], tokens2: set[str]
    ) -> tuple[bool, str]:
        """Check if token sets contain opposing polarity terms or direct negation."""
        for positive_set, negative_set in OPPOSING_POLARITY_PAIRS:
            pos1, neg1 = bool(tokens1 & positive_set), bool(tokens1 & negative_set)
            pos2, neg2 = bool(tokens2 & positive_set), bool(tokens2 & negative_set)

            if (pos1 and neg2) or (neg1 and pos2):
                pos_word = next(
                    iter(tokens1 & positive_set or tokens2 & positive_set),
                    "affirmative",
                )
                neg_word = next(
                    iter(tokens1 & negative_set or tokens2 & negative_set), "opposing"
                )
                return True, f"Opposing terms detected: '{pos_word}' vs '{neg_word}'"

        # Check direct negation divergence
        has_neg1 = bool(tokens1 & NEGATION_TOKENS)
        has_neg2 = bool(tokens2 & NEGATION_TOKENS)
        if has_neg1 != has_neg2:
            shared_content = (tokens1 - NEGATION_TOKENS) & (tokens2 - NEGATION_TOKENS)
            if len(shared_content) >= self.min_word_overlap:
                return (
                    True,
                    f"Direct negation divergence on core concept: {', '.join(sorted(shared_content)[:3])}",
                )

        return False, ""

    async def detect_contradictions(
        self,
        claims: list[ExtractedClaim],
        run_id: str,
    ) -> ContradictionDetectionResult:
        """Evaluate pairwise claims for mutual divergence with strict run isolation."""
        if claims is None or not isinstance(claims, list):
            raise TypeError("claims must be a list of ExtractedClaim instances")

        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty or whitespace only")
        clean_run_id = run_id.strip()

        if not claims:
            return ContradictionDetectionResult(
                run_id=clean_run_id,
                contradictions=(),
                claims_evaluated=0,
                total_contradictions=0,
                has_contradictions=False,
            )

        # Validate claims and enforce run isolation
        seen_claim_ids: set[str] = set()
        deduplicated_claims: list[ExtractedClaim] = []

        for claim in claims:
            if not isinstance(claim, ExtractedClaim):
                raise TypeError(f"Expected ExtractedClaim, got {type(claim).__name__}")

            if claim.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Claim '{claim.claim_id}' has run_id '{claim.run_id}' "
                    f"which does not match contradiction detection run_id '{clean_run_id}'"
                )

            if claim.claim_id not in seen_claim_ids:
                seen_claim_ids.add(claim.claim_id)
                deduplicated_claims.append(claim)

        # Pairwise evaluation (prevent self-comparison and canonical pair ordering)
        detected_contradictions: list[ContradictionItem] = []
        evaluated_pairs: set[tuple[str, str]] = set()

        for i in range(len(deduplicated_claims)):
            for j in range(i + 1, len(deduplicated_claims)):
                c1 = deduplicated_claims[i]
                c2 = deduplicated_claims[j]

                # Canonical pair ordering (avoids A-B / B-A duplication)
                c_min_id, c_max_id = (
                    min(c1.claim_id, c2.claim_id),
                    max(c1.claim_id, c2.claim_id),
                )
                pair_key = (c_min_id, c_max_id)
                if pair_key in evaluated_pairs:
                    continue
                evaluated_pairs.add(pair_key)

                tokens1 = self._tokenize(c1.statement)
                tokens2 = self._tokenize(c2.statement)

                # Check topic / keyword overlap
                shared_topics = (
                    bool(set(c1.topic_tags) & set(c2.topic_tags))
                    if c1.topic_tags and c2.topic_tags
                    else False
                )
                shared_words = tokens1 & tokens2
                is_related = shared_topics or len(shared_words) >= self.min_word_overlap

                if not is_related:
                    continue

                is_contradiction, reason = self._detect_polarity_clash(tokens1, tokens2)
                if not is_contradiction:
                    continue

                # Build contradiction record
                conflicting_evidence = tuple(
                    sorted(
                        {ev_id for c in (c1, c2) for ev_id in c.supporting_evidence_ids}
                    )
                )

                if not conflicting_evidence:
                    raise ContradictionDetectionError(
                        f"Contradiction between {c1.claim_id} and {c2.claim_id} lacks supporting evidence"
                    )

                severity = round(min(c1.confidence_score, c2.confidence_score), 3)
                is_untrusted = c1.is_untrusted or c2.is_untrusted
                is_quarantined = c1.is_quarantined or c2.is_quarantined

                item_id = _deterministic_item_id(clean_run_id, c_min_id, c_max_id)
                description = (
                    f"Factual divergence between '{c1.statement.rstrip('.')}' and "
                    f"'{c2.statement.rstrip('.')}': {reason}"
                )
                analysis = (
                    f"Sources disagree on core proposition. Evidence '{', '.join(conflicting_evidence)}' "
                    f"presents conflicting assertions ({reason})."
                )

                item = ContradictionItem(
                    item_id=item_id,
                    run_id=clean_run_id,
                    description=description,
                    conflicting_claim_ids=(c_min_id, c_max_id),
                    conflicting_evidence_ids=conflicting_evidence,
                    divergence_analysis=analysis,
                    severity_score=severity,
                    is_untrusted=is_untrusted,
                    is_quarantined=is_quarantined,
                    metadata={"reason": reason},
                )
                detected_contradictions.append(item)

        # Deterministic sorting by (-severity_score, claim_id_1, claim_id_2)
        detected_contradictions.sort(
            key=lambda item: (
                -round(item.severity_score, 3),
                item.conflicting_claim_ids[0],
                item.conflicting_claim_ids[1],
            )
        )

        return ContradictionDetectionResult(
            run_id=clean_run_id,
            contradictions=tuple(detected_contradictions),
            claims_evaluated=len(deduplicated_claims),
            total_contradictions=len(detected_contradictions),
            has_contradictions=len(detected_contradictions) > 0,
        )


__all__ = [
    "ContradictionDetectionResult",
    "ContradictionDetector",
    "ContradictionDetectorProtocol",
    "generate_contradiction_id",
]

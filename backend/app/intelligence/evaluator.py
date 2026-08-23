"""Evaluator agent, research quality metrics, and rigorous self-critique audits.

Computes multi-dimensional quality rubrics including completeness, citation coverage,
contradiction rates, and source diversity to produce formal EvaluationReport records.
"""

import re
import uuid
from typing import Protocol, runtime_checkable

from app.common.errors import (
    EvaluationError,
    EvidenceValidationError,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
)


def generate_eval_id(prefix: str = "eval") -> str:
    """Generate a unique evaluation report identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@runtime_checkable
class EvaluatorProtocol(Protocol):
    """Protocol for evaluating research synthesis quality and rigor."""

    async def evaluate_research(
        self,
        goal_query: str,
        findings: list[KeyFinding],
        claims: list[ExtractedClaim],
        citations: list[CitationReference],
        contradictions: list[ContradictionItem],
        run_id: str,
        plan_id: str = "plan_default",
    ) -> EvaluationReport:
        """Conduct self-evaluation and generate formal quality audit."""
        ...


class EvaluatorAgent(EvaluatorProtocol):
    """Deterministic evaluator agent computing quantitative quality rubrics and self-critique."""

    def __init__(
        self,
        pass_threshold: float = 0.70,
        min_citation_coverage: float = 0.50,
    ) -> None:
        if not 0.0 <= pass_threshold <= 1.0:
            raise EvidenceValidationError(
                f"pass_threshold must be between 0.0 and 1.0, got {pass_threshold}"
            )
        if not 0.0 <= min_citation_coverage <= 1.0:
            raise EvidenceValidationError(
                f"min_citation_coverage must be between 0.0 and 1.0, got {min_citation_coverage}"
            )
        self.pass_threshold = pass_threshold
        self.min_citation_coverage = min_citation_coverage

    def _tokenize(self, text: str) -> set[str]:
        words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
        return {w for w in words if len(w) > 2}

    async def evaluate_research(
        self,
        goal_query: str,
        findings: list[KeyFinding],
        claims: list[ExtractedClaim],
        citations: list[CitationReference],
        contradictions: list[ContradictionItem],
        run_id: str,
        plan_id: str = "plan_default",
    ) -> EvaluationReport:
        """Evaluate synthesized research rigor against inquiry goal with strict run isolation."""
        if not goal_query or not goal_query.strip():
            raise EvaluationError(
                "goal_query must not be empty or whitespace only",
                code="EMPTY_GOAL_QUERY",
            )
        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty or whitespace only")
        clean_run_id = run_id.strip()

        if (
            not isinstance(findings, list)
            or not isinstance(claims, list)
            or not isinstance(citations, list)
            or not isinstance(contradictions, list)
        ):
            raise TypeError(
                "findings, claims, citations, and contradictions must be lists"
            )

        # Enforce strict multi-tenant run isolation
        for f in findings:
            if not isinstance(f, KeyFinding):
                raise TypeError(f"Expected KeyFinding, got {type(f).__name__}")
            if f.run_id and f.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Finding '{f.finding_id}' run_id '{f.run_id}' does not match '{clean_run_id}'"
                )

        for c in claims:
            if not isinstance(c, ExtractedClaim):
                raise TypeError(f"Expected ExtractedClaim, got {type(c).__name__}")
            if c.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Claim '{c.claim_id}' run_id '{c.run_id}' does not match '{clean_run_id}'"
                )

        for cit in citations:
            if not isinstance(cit, CitationReference):
                raise TypeError(f"Expected CitationReference, got {type(cit).__name__}")
            if cit.run_id and cit.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Citation '{cit.citation_key}' run_id '{cit.run_id}' does not match '{clean_run_id}'"
                )

        for cnt in contradictions:
            if not isinstance(cnt, ContradictionItem):
                raise TypeError(f"Expected ContradictionItem, got {type(cnt).__name__}")
            if cnt.run_id and cnt.run_id != clean_run_id:
                raise EvidenceValidationError(
                    f"Contradiction '{cnt.item_id}' run_id '{cnt.run_id}' does not match '{clean_run_id}'"
                )

        # 1. Completeness / Goal Coverage Score
        goal_tokens = self._tokenize(goal_query)
        findings_text = " ".join(f"{f.title} {f.narrative}" for f in findings)
        findings_tokens = self._tokenize(findings_text)

        if not findings:
            completeness = 0.0
        elif not goal_tokens:
            completeness = 1.0
        else:
            overlap = len(goal_tokens & findings_tokens)
            # Base completeness from findings presence + keyword coverage
            completeness = round(min(1.0, 0.4 + 0.6 * (overlap / len(goal_tokens))), 3)

        # 2. Citation Coverage Score & Unsupported Claim Rate
        cited_evidence_ids = {cit.evidence_id for cit in citations}
        if not claims:
            citation_coverage = 0.0 if not findings else 1.0
        else:
            grounded_claims_count = sum(
                1
                for c in claims
                if any(
                    ev_id in cited_evidence_ids for ev_id in c.supporting_evidence_ids
                )
            )
            citation_coverage = round(grounded_claims_count / len(claims), 3)

        unsupported_rate = round(1.0 - citation_coverage, 3)

        # 3. Contradiction Rate
        total_claims_denom = max(1, len(claims))
        contradiction_rate = round(
            min(1.0, len(contradictions) / total_claims_denom), 3
        )

        # 4. Source Diversity Score
        unique_domains = {cit.domain for cit in citations if cit.domain}
        diversity = round(min(1.0, len(unique_domains) / 3.0), 3) if citations else 0.0

        # Rubric Breakdown
        rubrics = (
            EvaluationRubricScore(
                rubric_name="Groundedness & Citation Coverage",
                score=citation_coverage,
                weight=0.35,
                feedback=f"Grounded claim ratio is {citation_coverage * 100:.1f}%.",
            ),
            EvaluationRubricScore(
                rubric_name="Goal Inquiry Completeness",
                score=completeness,
                weight=0.35,
                feedback=f"Inquiry coverage across goal keywords is {completeness * 100:.1f}%.",
            ),
            EvaluationRubricScore(
                rubric_name="Contradiction Coherence",
                score=round(max(0.0, 1.0 - contradiction_rate), 3),
                weight=0.15,
                feedback=f"Contradiction proportion is {contradiction_rate * 100:.1f}%.",
            ),
            EvaluationRubricScore(
                rubric_name="Source Diversity",
                score=diversity,
                weight=0.15,
                feedback=f"Distinct source domain count: {len(unique_domains)}.",
            ),
        )

        # Overall Composite Rating
        overall_score = round(
            0.35 * citation_coverage
            + 0.35 * completeness
            + 0.15 * max(0.0, 1.0 - contradiction_rate)
            + 0.15 * diversity,
            3,
        )

        passed = (
            overall_score >= self.pass_threshold
            and citation_coverage >= self.min_citation_coverage
            and len(findings) > 0
        )

        critique = (
            f"Research evaluation {'PASSED' if passed else 'FAILED'} with overall score {overall_score:.2f}. "
            f"Groundedness: {citation_coverage:.2f}, Completeness: {completeness:.2f}, "
            f"Contradictions: {len(contradictions)}, Citations: {len(citations)}."
        )

        report_id = f"eval_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{plan_id}').hex[:16]}"

        return EvaluationReport(
            report_id=report_id,
            run_id=clean_run_id,
            plan_id=plan_id,
            passed=passed,
            overall_score=overall_score,
            completeness_score=completeness,
            citation_coverage_score=citation_coverage,
            contradiction_rate=contradiction_rate,
            unsupported_claim_rate=unsupported_rate,
            source_diversity_score=diversity,
            rubric_scores=rubrics,
            summary_critique=critique,
        )


__all__ = [
    "EvaluatorAgent",
    "EvaluatorProtocol",
    "generate_eval_id",
]

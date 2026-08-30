"""Reporter agent and publication-grade ResearchDossier compilation layer.

Compiles synthesized key findings, verified factual claims, citation indexes,
contradictions, and quality evaluation audits into structured, immutable ResearchDossier
artifacts and publication-ready Markdown dossiers that directly answer the user's research inquiry.
"""

import re
import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import VerificationStatus
from app.common.errors import (
    EvidenceValidationError,
    ReportingError,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    KeyFinding,
    ResearchDossier,
)
from app.intelligence.protocols import LLMClientProtocol


def generate_dossier_id(prefix: str = "dos") -> str:
    """Generate a unique identifier for a ResearchDossier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class SynthesisOutput(BaseModel):
    """Structured LLM synthesis output schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direct_answer: str = Field(
        ...,
        min_length=1,
        description="Concise direct answer addressing the research inquiry",
    )
    thematic_sections: tuple[str, ...] = Field(
        default_factory=tuple, description="Evidence-backed breakdown sections"
    )
    uncertainties_and_limitations: tuple[str, ...] = Field(
        default_factory=tuple, description="Empirical limitations and gaps in evidence"
    )


@runtime_checkable
class ReporterProtocol(Protocol):
    """Protocol for compiling comprehensive research dossiers."""

    async def compile_dossier(
        self,
        goal_query: str,
        findings: list[KeyFinding],
        claims: list[ExtractedClaim],
        citations: list[CitationReference],
        contradictions: list[ContradictionItem],
        run_id: str,
        evaluation: EvaluationReport | None = None,
        methodology_summary: str = "",
        limitations: list[str] | None = None,
    ) -> ResearchDossier:
        """Compile a full publication-grade research dossier deliverable."""
        ...


class ReporterAgent(ReporterProtocol):
    """Publication-grade reporter agent synthesizing evidence-grounded answers to research questions."""

    def __init__(self, llm_client: LLMClientProtocol | None = None) -> None:
        self.llm_client = llm_client

    def _deduplicate_findings(self, findings: list[KeyFinding]) -> list[KeyFinding]:
        """Deduplicate findings with identical or near-identical titles/narratives and merge evidence."""
        seen: dict[str, KeyFinding] = {}

        for f in findings:
            # Normalize title for grouping
            norm_key = re.sub(r"\s+", " ", f.title.strip().lower())
            if norm_key in seen:
                existing = seen[norm_key]
                merged_claim_ids = tuple(sorted(set(existing.claim_ids + f.claim_ids)))
                merged_evidence_ids = tuple(
                    sorted(set(existing.evidence_ids + f.evidence_ids))
                )
                max_conf = max(existing.confidence_score, f.confidence_score)
                chosen_narrative = (
                    f.narrative
                    if len(f.narrative) > len(existing.narrative)
                    else existing.narrative
                )

                seen[norm_key] = KeyFinding(
                    finding_id=existing.finding_id,
                    run_id=existing.run_id,
                    title=existing.title,
                    narrative=chosen_narrative,
                    claim_ids=merged_claim_ids,
                    evidence_ids=merged_evidence_ids,
                    confidence_score=max_conf,
                    is_untrusted=existing.is_untrusted or f.is_untrusted,
                    is_quarantined=existing.is_quarantined or f.is_quarantined,
                    metadata={**existing.metadata, **f.metadata},
                )
            else:
                seen[norm_key] = f

        return list(seen.values())

    def _generate_deterministic_answer(
        self,
        goal_query: str,
        findings: list[KeyFinding],
        claims: list[ExtractedClaim],
    ) -> str:
        """Construct a coherent, direct answer answering the user's research inquiry from findings."""
        if not findings and not claims:
            return f"Evidence is currently insufficient to establish definitive empirical conclusions for: '{goal_query}'."

        answer_parts: list[str] = []
        for f in findings:
            answer_parts.append(f"{f.title}: {f.narrative}")

        if not answer_parts and claims:
            top_claims = [c.statement.rstrip(".") for c in claims[:3]]
            answer_parts.append(". ".join(top_claims) + ".")

        return " ".join(answer_parts)

    def _generate_markdown(
        self,
        goal_query: str,
        direct_answer: str,
        methodology_summary: str,
        findings: list[KeyFinding],
        claims: list[ExtractedClaim],
        citations: list[CitationReference],
        contradictions: list[ContradictionItem],
        evaluation: EvaluationReport | None,
        limitations: list[str],
    ) -> str:
        """Render publication-grade Markdown text."""
        lines: list[str] = [
            f"# Research Dossier: {goal_query}",
            "",
            "## Executive Summary",
            direct_answer,
            "",
            "## Key Thematic Findings",
        ]

        # Citation lookup
        cit_lookup = {c.evidence_id: c.citation_key for c in citations}

        if findings:
            for idx, f in enumerate(findings, start=1):
                inline_cits = [
                    cit_lookup[ev_id] for ev_id in f.evidence_ids if ev_id in cit_lookup
                ]
                cit_suffix = f" {' '.join(inline_cits)}" if inline_cits else ""
                lines.extend(
                    [
                        f"### {idx}. {f.title}",
                        f"{f.narrative}{cit_suffix}",
                        f"- **Confidence**: {f.confidence_score:.2f} | **Supporting Claims**: {len(f.claim_ids)} | **Evidence Sources**: {len(f.evidence_ids)}",
                        "",
                    ]
                )
        else:
            lines.extend(["*No synthesized thematic findings available.*", ""])

        if claims:
            lines.extend(["## Factual Claims & Grounding", ""])
            for c in claims:
                c_cits = [
                    cit_lookup[ev_id]
                    for ev_id in c.supporting_evidence_ids
                    if ev_id in cit_lookup
                ]
                c_suffix = f" ({', '.join(c_cits)})" if c_cits else ""
                lines.append(
                    f"- **[{c.claim_id}]** {c.statement}{c_suffix} *(Confidence: {c.confidence_score:.2f})*"
                )
            lines.append("")

        if contradictions:
            lines.extend(["## Documented Contradictions & Divergent Perspectives", ""])
            for cnt in contradictions:
                lines.extend(
                    [
                        f"### Conflict: {cnt.item_id}",
                        f"- **Summary**: {cnt.description}",
                        f"- **Analysis**: {cnt.divergence_analysis}",
                        f"- **Conflicting Claims**: {', '.join(cnt.conflicting_claim_ids)}",
                        f"- **Severity**: {cnt.severity_score:.2f}",
                        "",
                    ]
                )

        lines.extend(["## Comprehensive Bibliography & Sources", ""])
        if citations:
            for cit in citations:
                pub_info = f" ({cit.publication_date})" if cit.publication_date else ""
                lines.append(
                    f"- **{cit.citation_key}** [{cit.title}]({cit.source_url}){pub_info} — *{cit.domain}* (Trust: `{cit.trust_level.value}`)"
                )
        else:
            lines.append("*No external citations referenced.*")
        lines.append("")

        if limitations:
            lines.extend(["## Research Limitations & Empirical Boundaries", ""])
            for lim in limitations:
                lines.append(f"- {lim}")
            lines.append("")

        lines.extend(
            [
                "## Methodology Summary",
                methodology_summary
                or "Autonomous multi-agent inquiry with topological subtask scheduling, empirical evidence grounding, and cryptographic state verification.",
                "",
            ]
        )

        if evaluation:
            lines.extend(
                [
                    "## Quality Audit & Self-Evaluation",
                    f"- **Overall Quality Score**: {evaluation.overall_score:.2f} ({'PASSED' if evaluation.passed else 'FAILED'})",
                    f"- **Inquiry Completeness**: {evaluation.completeness_score:.2f}",
                    f"- **Citation Coverage**: {evaluation.citation_coverage_score:.2f}",
                    f"- **Contradiction Rate**: {evaluation.contradiction_rate:.2f}",
                    f"- **Source Diversity**: {evaluation.source_diversity_score:.2f}",
                    f"- **Critique**: {evaluation.summary_critique}",
                    "",
                ]
            )

        return "\n".join(lines)

    async def compile_dossier(
        self,
        goal_query: str,
        findings: list[KeyFinding],
        claims: list[ExtractedClaim],
        citations: list[CitationReference],
        contradictions: list[ContradictionItem],
        run_id: str,
        evaluation: EvaluationReport | None = None,
        methodology_summary: str = "",
        limitations: list[str] | None = None,
    ) -> ResearchDossier:
        """Compile verified findings and evaluation into a complete ResearchDossier."""
        if not goal_query or not goal_query.strip():
            raise ReportingError("goal_query must not be empty", code="EMPTY_GOAL")

        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty")
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

        if evaluation and evaluation.run_id != clean_run_id:
            raise EvidenceValidationError(
                f"Evaluation report run_id '{evaluation.run_id}' does not match '{clean_run_id}'"
            )

        # 1. Deduplicate findings to eliminate redundant repetitions
        deduped_findings = self._deduplicate_findings(findings)

        # 2. Synthesize direct answer
        direct_answer: str
        if self.llm_client is not None:
            try:
                system_prompt = (
                    "You are an expert autonomous research scientist and investigator. "
                    "Synthesize a direct, evidence-grounded answer to the user's research inquiry based strictly on the provided claims and findings. "
                    "Directly address every major dimension of the inquiry. If evidence for any facet is missing, explicitly declare that evidence is insufficient."
                )
                evidence_summary = "\n".join(
                    [f"- Finding: {f.title}: {f.narrative}" for f in deduped_findings]
                    + [f"- Claim [{c.claim_id}]: {c.statement}" for c in claims[:10]]
                )
                user_prompt = (
                    f"Research Inquiry: {goal_query}\n\n"
                    f"Extracted Evidence & Findings:\n{evidence_summary}\n\n"
                    "Synthesize a clear, concise direct answer answering the inquiry."
                )
                from app.adapters.llm.base import LLMRequest

                resp = await self.llm_client.generate_text(
                    LLMRequest(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=0.2,
                    )
                )
                direct_answer = resp.content
            except Exception:
                direct_answer = self._generate_deterministic_answer(
                    goal_query, deduped_findings, claims
                )
        else:
            direct_answer = self._generate_deterministic_answer(
                goal_query, deduped_findings, claims
            )

        clean_limitations = (
            tuple(limitations)
            if limitations
            else ("Inquiry constrained by available public primary documents.",)
        )

        # Calculate overall confidence rating
        if evaluation:
            confidence = evaluation.overall_score
        elif deduped_findings:
            confidence = round(
                sum(f.confidence_score for f in deduped_findings)
                / len(deduped_findings),
                3,
            )
        else:
            confidence = 0.0

        # Determine verification status
        if contradictions:
            ver_status = VerificationStatus.CONTRADICTED
        elif citations and len(citations) >= len(deduped_findings):
            ver_status = VerificationStatus.VERIFIED
        elif deduped_findings:
            ver_status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            ver_status = VerificationStatus.UNVERIFIED

        markdown_doc = self._generate_markdown(
            goal_query=goal_query.strip(),
            direct_answer=direct_answer,
            methodology_summary=methodology_summary.strip(),
            findings=deduped_findings,
            claims=claims,
            citations=citations,
            contradictions=contradictions,
            evaluation=evaluation,
            limitations=list(clean_limitations),
        )

        dossier_id = f"dos_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{goal_query.strip()}').hex[:16]}"

        return ResearchDossier(
            dossier_id=dossier_id,
            run_id=clean_run_id,
            goal_query=goal_query.strip(),
            methodology_summary=methodology_summary.strip()
            or "Topological DAG execution with grounded claim verification.",
            executive_summary=direct_answer,
            key_findings=tuple(deduped_findings),
            claims=tuple(claims),
            citations=tuple(citations),
            contradictions=tuple(contradictions),
            limitations=clean_limitations,
            confidence_rating=confidence,
            verification_status=ver_status,
            evaluation=evaluation,
            markdown_report=markdown_doc,
        )


__all__ = [
    "ReporterAgent",
    "ReporterProtocol",
    "generate_dossier_id",
]

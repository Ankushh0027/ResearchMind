"""Reporter agent and publication-grade ResearchDossier compilation layer.

Compiles synthesized key findings, verified factual claims, citation indexes,
contradictions, and quality evaluation audits into structured, immutable ResearchDossier
artifacts and publication-ready Markdown dossiers.
"""

import uuid
from typing import Protocol, runtime_checkable

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


def generate_dossier_id(prefix: str = "dos") -> str:
    """Generate a unique identifier for a ResearchDossier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


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
    """Deterministic reporter agent formatting publication-ready research reports."""

    def _generate_markdown(
        self,
        goal_query: str,
        executive_summary: str,
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
            executive_summary,
            "",
            "## Methodology Summary",
            methodology_summary
            or "Autonomous multi-agent inquiry with topological subtask scheduling and cryptographic state verification.",
            "",
            "## Key Thematic Findings",
        ]

        # Citation lookup
        cit_lookup = {c.evidence_id: c.citation_key for c in citations}

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

        if limitations:
            lines.extend(["## Research Limitations", ""])
            for lim in limitations:
                lines.append(f"- {lim}")
            lines.append("")

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

        # Build executive summary
        if findings:
            top_narratives = [f"{f.title}: {f.narrative}" for f in findings[:3]]
            exec_summary = " ".join(top_narratives)
        else:
            exec_summary = "No synthesized findings generated for this research goal."

        clean_limitations = (
            tuple(limitations)
            if limitations
            else ("Inquiry constrained by available public primary documents.",)
        )

        # Calculate overall confidence rating
        if evaluation:
            confidence = evaluation.overall_score
        elif findings:
            confidence = round(
                sum(f.confidence_score for f in findings) / len(findings), 3
            )
        else:
            confidence = 0.0

        # Determine verification status
        if contradictions:
            ver_status = VerificationStatus.CONTRADICTED
        elif citations and len(citations) >= len(findings):
            ver_status = VerificationStatus.VERIFIED
        elif findings:
            ver_status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            ver_status = VerificationStatus.UNVERIFIED

        markdown_doc = self._generate_markdown(
            goal_query=goal_query.strip(),
            executive_summary=exec_summary,
            methodology_summary=methodology_summary.strip(),
            findings=findings,
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
            executive_summary=exec_summary,
            key_findings=tuple(findings),
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

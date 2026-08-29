"""Unit tests for the autonomous self-correction and refinement loop."""

from app.common.enums import (
    AgentRole,
    TaskType,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
)
from app.jobs.worker import ResearchJobWorker
from app.orchestration.refinement import (
    DeficiencyType,
    RefinementPlanner,
)
from app.orchestration.router import AgentWorkerRouter
from app.state.models import ResearchGoal
from app.tasks.dag import DAGValidator


def _make_dummy_eval_report(
    passed: bool = False,
    overall_score: float = 0.65,
    completeness_score: float = 0.70,
    citation_coverage_score: float = 0.60,
    contradiction_rate: float = 0.25,
    unsupported_claim_rate: float = 0.30,
    critique: str = "Incomplete analysis with unsupported assertions.",
) -> EvaluationReport:
    return EvaluationReport(
        report_id="rep_test_01",
        run_id="run_test_01",
        passed=passed,
        overall_score=overall_score,
        completeness_score=completeness_score,
        citation_coverage_score=citation_coverage_score,
        contradiction_rate=contradiction_rate,
        unsupported_claim_rate=unsupported_claim_rate,
        source_diversity_score=0.75,
        rubric_scores=(
            EvaluationRubricScore(
                rubric_name="Groundedness",
                score=0.60,
                weight=0.40,
                feedback="Several claims lack primary source evidence.",
            ),
            EvaluationRubricScore(
                rubric_name="Scope",
                score=0.70,
                weight=0.35,
                feedback="Omitted technical implementation details.",
            ),
        ),
        summary_critique=critique,
    )


class TestDeficiencyExtraction:
    """Validate parsing of evaluation reports into actionable deficiencies."""

    def test_extract_missing_topic_deficiency(self) -> None:
        report = _make_dummy_eval_report(completeness_score=0.60)
        defs = RefinementPlanner.extract_deficiencies(
            report, "Hybrid RAG vs Long-Context LLMs"
        )
        types = [d.deficiency_type for d in defs]
        assert DeficiencyType.MISSING_TOPIC in types

    def test_extract_unsupported_claims_deficiency(self) -> None:
        report = _make_dummy_eval_report(unsupported_claim_rate=0.40)
        defs = RefinementPlanner.extract_deficiencies(
            report, "Quantum Error Mitigation"
        )
        types = [d.deficiency_type for d in defs]
        assert DeficiencyType.UNSUPPORTED_CLAIM in types
        unsupported_def = next(
            d for d in defs if d.deficiency_type == DeficiencyType.UNSUPPORTED_CLAIM
        )
        assert unsupported_def.suggested_task_type == TaskType.ACADEMIC_SEARCH

    def test_extract_citation_deficiency(self) -> None:
        report = _make_dummy_eval_report(citation_coverage_score=0.50)
        defs = RefinementPlanner.extract_deficiencies(report, "Biomedical LNP Delivery")
        types = [d.deficiency_type for d in defs]
        assert DeficiencyType.CITATION_DEFICIENCY in types

    def test_extract_contradiction_deficiency(self) -> None:
        report = _make_dummy_eval_report(contradiction_rate=0.35)
        defs = RefinementPlanner.extract_deficiencies(
            report, "Wholesale CBDC Settlement"
        )
        types = [d.deficiency_type for d in defs]
        assert DeficiencyType.UNRESOLVED_CONTRADICTION in types

    def test_extract_rubric_critiques(self) -> None:
        report = _make_dummy_eval_report(
            completeness_score=0.90,
            citation_coverage_score=0.90,
            contradiction_rate=0.05,
            unsupported_claim_rate=0.05,
            overall_score=0.75,
        )
        defs = RefinementPlanner.extract_deficiencies(report, "Topic X")
        rubric_defs = [d for d in defs if d.deficiency_type.startswith("rubric_")]
        assert len(rubric_defs) >= 1

    def test_extract_fallback_low_quality(self) -> None:
        report = EvaluationReport(
            report_id="rep_test_fallback",
            run_id="run_test_01",
            passed=False,
            overall_score=0.70,
            completeness_score=0.90,
            citation_coverage_score=0.90,
            contradiction_rate=0.05,
            unsupported_claim_rate=0.05,
            source_diversity_score=0.90,
            rubric_scores=(),
            summary_critique="General stylistic weakness and shallow depth.",
        )
        defs = RefinementPlanner.extract_deficiencies(report, "General Inquiry")
        assert len(defs) == 1
        assert defs[0].deficiency_type == DeficiencyType.LOW_QUALITY


class TestRefinementPlanDAGConstruction:
    """Validate refinement plan formulation, DAG validity, and node lineage."""

    def test_create_refinement_plan_structure(self) -> None:
        report = _make_dummy_eval_report()
        goal = ResearchGoal(
            goal_id="g1",
            query="Analyze quantum error mitigation trade-offs",
        )
        refinement_plan = RefinementPlanner.create_refinement_plan(
            eval_report=report,
            iteration=1,
            run_id="run_01",
            goal=goal,
        )

        assert refinement_plan.iteration == 1
        assert refinement_plan.score_before == report.overall_score
        assert len(refinement_plan.deficiencies) > 0

        plan = refinement_plan.research_plan
        assert plan.run_id == "run_01"
        assert plan.version == 2
        assert plan.metadata.created_by_agent == "refinement_planner"

        # Validate DAG topological correctness
        validator = DAGValidator()
        validated_dag = validator.validate_plan(plan)
        assert validated_dag is not None

        # Verify node types present in refinement mesh
        roles = {n.assigned_role for n in plan.nodes.values()}
        assert AgentRole.RESEARCHER in roles
        assert AgentRole.ANALYST in roles
        assert AgentRole.VERIFIER in roles
        assert AgentRole.EVALUATOR in roles

        # Verify iteration metadata on nodes
        for node in plan.nodes.values():
            if node.assigned_role == AgentRole.RESEARCHER:
                assert node.input_context.get("refinement_iteration") == 1

    def test_second_iteration_plan_metadata(self) -> None:
        report = _make_dummy_eval_report(overall_score=0.78)
        goal = ResearchGoal(
            goal_id="g2",
            query="Biomedical gene editing analysis",
        )
        refinement_plan = RefinementPlanner.create_refinement_plan(
            eval_report=report,
            iteration=2,
            run_id="run_02",
            goal=goal,
        )

        assert refinement_plan.iteration == 2
        assert refinement_plan.research_plan.version == 3
        assert (
            "iteration 2"
            in (refinement_plan.research_plan.metadata.notes or "").lower()
        )


class TestWorkerRefinementHelpers:
    """Validate helper methods on ResearchJobWorker for evidence aggregation and telemetry."""

    def test_extract_eval_report_helper(self) -> None:
        worker = ResearchJobWorker(router=AgentWorkerRouter())
        report = _make_dummy_eval_report()
        task_outputs = {
            "task_res": {"evidence": []},
            "task_eval": report.model_dump(),
        }
        extracted = worker._extract_eval_report(task_outputs)
        assert extracted is not None
        assert extracted.report_id == "rep_test_01"
        assert extracted.overall_score == 0.65

    def test_extract_findings_claims_citations_helper(self) -> None:
        worker = ResearchJobWorker(router=AgentWorkerRouter())
        finding = KeyFinding(
            finding_id="kf_1",
            title="Finding 1",
            narrative="Narrative 1",
            run_id="run_01",
        )
        claim = ExtractedClaim(
            claim_id="clm_1",
            statement="Claim 1",
            confidence_score=0.9,
            supporting_evidence_ids=("ev_01",),
            run_id="run_01",
        )
        citation = CitationReference(
            citation_key="[CIT-01]",
            evidence_id="ev_01",
            source_url="https://example.com",
            title="Source 1",
            domain="example.com",
            run_id="run_01",
        )
        contradiction = ContradictionItem(
            item_id="cnt_1",
            description="Conflict between claims",
            conflicting_claim_ids=("clm_1", "clm_2"),
            divergence_analysis="Methodological differences.",
            run_id="run_01",
        )

        task_outputs = {
            "task_an": {
                "findings": [finding.model_dump()],
                "claims": [claim.model_dump()],
            },
            "task_ver": {
                "citations": [citation.model_dump()],
                "contradictions": [contradiction.model_dump()],
            },
        }

        findings = worker._extract_all_findings(task_outputs)
        claims = worker._extract_all_claims(task_outputs)
        citations = worker._extract_all_citations(task_outputs)
        contradictions = worker._extract_all_contradictions(task_outputs)

        assert len(findings) == 1
        assert findings[0]["finding_id"] == "kf_1"
        assert len(claims) == 1
        assert claims[0]["claim_id"] == "clm_1"
        assert len(citations) == 1
        assert citations[0]["citation_key"] == "[CIT-01]"
        assert len(contradictions) == 1
        assert contradictions[0]["item_id"] == "cnt_1"

    def test_record_refinement_telemetry_safe(self) -> None:
        worker = ResearchJobWorker(router=AgentWorkerRouter())
        # Verify no exception is raised
        worker._record_refinement_telemetry(
            run_id="run_telemetry_test",
            iteration=1,
            score=0.88,
            event="completed",
        )

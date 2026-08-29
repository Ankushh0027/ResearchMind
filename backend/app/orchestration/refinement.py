"""Dynamic self-correction and targeted inquiry refinement planner."""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import AgentRole, EdgeType, TaskType
from app.intelligence.models import EvaluationReport
from app.state.models import (
    DependencyEdge,
    PlanMetadata,
    ResearchGoal,
    ResearchPlan,
    SubtaskNode,
)


class DeficiencyType:
    """Classifications of research deficiencies identified during evaluation."""

    MISSING_TOPIC = "missing_topic"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CITATION_DEFICIENCY = "citation_deficiency"
    UNRESOLVED_CONTRADICTION = "unresolved_contradiction"
    LOW_QUALITY = "low_quality"


class EvaluationDeficiency(BaseModel):
    """Structured deficiency extracted from an evaluation report critique."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deficiency_type: str = Field(..., description="Classification of the deficiency")
    description: str = Field(
        ..., min_length=1, description="Explanation of what is missing or flawed"
    )
    target_query: str = Field(
        ..., min_length=1, description="Actionable search query to address deficiency"
    )
    weight: float = Field(
        default=1.0, ge=0.0, description="Severity weight of this deficiency"
    )
    suggested_task_type: TaskType = Field(
        default=TaskType.WEB_SEARCH, description="Target task type"
    )
    suggested_role: AgentRole = Field(
        default=AgentRole.RESEARCHER, description="Assigned agent role"
    )


class RefinementPlan(BaseModel):
    """Container holding formulated refinement tasks, provenance, and executable research plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(..., description="Unique refinement plan identifier")
    run_id: str = Field(..., description="Associated research run ID")
    iteration: int = Field(..., ge=1, description="Refinement cycle count (1-indexed)")
    score_before: float = Field(
        ..., ge=0.0, le=1.0, description="Evaluation score prior to refinement"
    )
    deficiencies: tuple[EvaluationDeficiency, ...] = Field(
        default_factory=tuple, description="Deficiencies addressed in this iteration"
    )
    research_plan: ResearchPlan = Field(..., description="Executable DAG research plan")
    provenance: dict[str, Any] = Field(
        default_factory=dict, description="Audit trail and provenance linking"
    )


class RefinementPlanner:
    """Generates targeted refinement subtasks and DAG execution plans from evaluation critiques."""

    @classmethod
    def extract_deficiencies(
        cls, eval_report: EvaluationReport, goal_query: str
    ) -> list[EvaluationDeficiency]:
        """Parse structured metrics and rubric critiques into targeted, actionable deficiencies."""
        deficiencies: list[EvaluationDeficiency] = []

        # 1. Missing Subtopics / Low Completeness
        if eval_report.completeness_score < 0.85:
            # Extract topic clues from critique or goal_query
            query = f"{goal_query} in-depth analysis evidence"
            deficiencies.append(
                EvaluationDeficiency(
                    deficiency_type=DeficiencyType.MISSING_TOPIC,
                    description=f"Inquiry completeness score ({eval_report.completeness_score:.2f}) below threshold.",
                    target_query=query,
                    weight=0.35,
                    suggested_task_type=TaskType.WEB_SEARCH,
                    suggested_role=AgentRole.RESEARCHER,
                )
            )

        # 2. Unsupported Claims / Weak Grounding
        if eval_report.unsupported_claim_rate > 0.15:
            query = f"{goal_query} empirical evidence primary findings verification"
            deficiencies.append(
                EvaluationDeficiency(
                    deficiency_type=DeficiencyType.UNSUPPORTED_CLAIM,
                    description=f"High rate of ungrounded or unsupported claims ({eval_report.unsupported_claim_rate:.2%}).",
                    target_query=query,
                    weight=0.40,
                    suggested_task_type=TaskType.ACADEMIC_SEARCH,
                    suggested_role=AgentRole.RESEARCHER,
                )
            )

        # 3. Citation Coverage Deficiency
        if eval_report.citation_coverage_score < 0.85:
            query = f"{goal_query} authoritative academic citations peer-reviewed literature"
            deficiencies.append(
                EvaluationDeficiency(
                    deficiency_type=DeficiencyType.CITATION_DEFICIENCY,
                    description=f"Low citation coverage score ({eval_report.citation_coverage_score:.2%}).",
                    target_query=query,
                    weight=0.25,
                    suggested_task_type=TaskType.ACADEMIC_SEARCH,
                    suggested_role=AgentRole.RESEARCHER,
                )
            )

        # 4. Unresolved Contradictions
        if eval_report.contradiction_rate > 0.15:
            query = f"{goal_query} conflicting perspectives debate trade-offs"
            deficiencies.append(
                EvaluationDeficiency(
                    deficiency_type=DeficiencyType.UNRESOLVED_CONTRADICTION,
                    description=f"Unresolved factual contradictions detected ({eval_report.contradiction_rate:.2%}).",
                    target_query=query,
                    weight=0.25,
                    suggested_task_type=TaskType.DOC_ANALYSIS,
                    suggested_role=AgentRole.RESEARCHER,
                )
            )

        # 5. Granular Rubric Critiques
        for rubric in eval_report.rubric_scores:
            if rubric.score < 0.80:
                # Clean feedback string for a concise query
                clean_feedback = re.sub(r"[^\w\s]", " ", rubric.feedback)
                words = [w for w in clean_feedback.split() if len(w) > 3][:6]
                rubric_query = " ".join(words) or goal_query
                deficiencies.append(
                    EvaluationDeficiency(
                        deficiency_type=f"rubric_{rubric.rubric_name.lower().replace(' ', '_')}",
                        description=f"Rubric '{rubric.rubric_name}' score ({rubric.score:.2f}) deduction: {rubric.feedback}",
                        target_query=f"{goal_query} {rubric_query}",
                        weight=rubric.weight,
                        suggested_task_type=TaskType.WEB_SEARCH,
                        suggested_role=AgentRole.RESEARCHER,
                    )
                )

        # 6. Fallback if overall score is low but no individual metric triggered
        if not deficiencies and eval_report.overall_score < 0.85:
            deficiencies.append(
                EvaluationDeficiency(
                    deficiency_type=DeficiencyType.LOW_QUALITY,
                    description=f"Overall quality score ({eval_report.overall_score:.2f}) below threshold: {eval_report.summary_critique}",
                    target_query=f"{goal_query} detailed comprehensive analysis",
                    weight=1.0,
                    suggested_task_type=TaskType.WEB_SEARCH,
                    suggested_role=AgentRole.RESEARCHER,
                )
            )

        return deficiencies

    @classmethod
    def create_refinement_plan(
        cls,
        eval_report: EvaluationReport,
        iteration: int,
        run_id: str,
        goal: ResearchGoal,
        plan_id: str | None = None,
    ) -> RefinementPlan:
        """Formulate a complete, executable DAG ResearchPlan targeting evaluation deficiencies."""
        actual_plan_id = plan_id or f"plan_refine_{run_id}_iter{iteration}"
        deficiencies = cls.extract_deficiencies(eval_report, goal.query)

        nodes: dict[str, SubtaskNode] = {}
        edges: list[DependencyEdge] = []
        research_node_ids: list[str] = []

        # 1. Generate targeted research subtasks from deficiencies (capped at max 4 per iteration)
        for idx, def_item in enumerate(deficiencies[:4]):
            task_id = f"task_refine_{iteration}_res_{idx + 1}"
            nodes[task_id] = SubtaskNode(
                subtask_id=task_id,
                task_type=def_item.suggested_task_type,
                objective=f"Refinement iter {iteration}: {def_item.description}",
                search_queries=(def_item.target_query,),
                assigned_role=def_item.suggested_role,
                input_context={
                    "goal_query": goal.query,
                    "refinement_iteration": iteration,
                    "deficiency_type": def_item.deficiency_type,
                    "deficiency_description": def_item.description,
                },
            )
            research_node_ids.append(task_id)

        # Fallback if no research node generated
        if not research_node_ids:
            fallback_id = f"task_refine_{iteration}_res_fallback"
            nodes[fallback_id] = SubtaskNode(
                subtask_id=fallback_id,
                task_type=TaskType.WEB_SEARCH,
                objective=f"Refinement iter {iteration}: Gather missing evidence",
                search_queries=(f"{goal.query} comprehensive evidence",),
                assigned_role=AgentRole.RESEARCHER,
                input_context={"refinement_iteration": iteration},
            )
            research_node_ids.append(fallback_id)

        # 2. Downstream Analyst Node (Re-Synthesis)
        an_id = f"task_refine_{iteration}_an"
        nodes[an_id] = SubtaskNode(
            subtask_id=an_id,
            task_type=TaskType.SYNTHESIS,
            objective=f"Refinement iter {iteration}: Re-synthesize refined claims with new evidence",
            assigned_role=AgentRole.ANALYST,
            input_context={"goal_query": goal.query, "refinement_iteration": iteration},
        )
        for rid in research_node_ids:
            edges.append(
                DependencyEdge(source_id=rid, target_id=an_id, edge_type=EdgeType.DATA)
            )

        # 3. Downstream Verifier Node (Re-Verification)
        ver_id = f"task_refine_{iteration}_ver"
        nodes[ver_id] = SubtaskNode(
            subtask_id=ver_id,
            task_type=TaskType.VERIFICATION,
            objective=f"Refinement iter {iteration}: Re-verify refined claims and check citations",
            assigned_role=AgentRole.VERIFIER,
            input_context={"goal_query": goal.query, "refinement_iteration": iteration},
        )
        for rid in research_node_ids:
            edges.append(
                DependencyEdge(source_id=rid, target_id=ver_id, edge_type=EdgeType.DATA)
            )
        edges.append(
            DependencyEdge(source_id=an_id, target_id=ver_id, edge_type=EdgeType.DATA)
        )

        # 4. Downstream Evaluator Node (Re-Evaluation)
        eval_id = f"task_refine_{iteration}_eval"
        nodes[eval_id] = SubtaskNode(
            subtask_id=eval_id,
            task_type=TaskType.EVALUATION,
            objective=f"Refinement iter {iteration}: Re-evaluate refined synthesis quality",
            assigned_role=AgentRole.EVALUATOR,
            input_context={"goal_query": goal.query, "refinement_iteration": iteration},
        )
        edges.append(
            DependencyEdge(source_id=an_id, target_id=eval_id, edge_type=EdgeType.DATA)
        )
        edges.append(
            DependencyEdge(source_id=ver_id, target_id=eval_id, edge_type=EdgeType.DATA)
        )

        research_plan = ResearchPlan(
            plan_id=actual_plan_id,
            run_id=run_id,
            goal=goal,
            nodes=nodes,
            edges=tuple(edges),
            metadata=PlanMetadata(
                created_by_agent="refinement_planner",
                total_estimated_depth=4,
                notes=(
                    f"Refinement iteration {iteration} targeting {len(deficiencies)} "
                    f"evaluation deficiencies (prior score: {eval_report.overall_score:.3f})"
                ),
            ),
            version=iteration + 1,
        )

        return RefinementPlan(
            plan_id=actual_plan_id,
            run_id=run_id,
            iteration=iteration,
            score_before=eval_report.overall_score,
            deficiencies=tuple(deficiencies),
            research_plan=research_plan,
            provenance={
                "prior_report_id": eval_report.report_id,
                "prior_score": eval_report.overall_score,
                "deficiency_count": len(deficiencies),
            },
        )


__all__ = [
    "DeficiencyType",
    "EvaluationDeficiency",
    "RefinementPlan",
    "RefinementPlanner",
]

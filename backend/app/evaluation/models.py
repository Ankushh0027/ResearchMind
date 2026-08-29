"""Domain models and schemas for automated quality evaluation and benchmark suites."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GroundTruthFact(BaseModel):
    """Normalized factual claim expected in synthesized research dossiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str = Field(..., min_length=1, description="Unique fact identifier")
    claim: str = Field(..., min_length=1, description="Ground truth factual claim text")
    normalized_claim: str = Field(
        default="", description="Pre-normalized claim tokens for fast matching"
    )
    is_required: bool = Field(
        default=True,
        description="Whether this fact is strictly required for completeness",
    )
    supporting_citation_keys: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Expected canonical citation keys or URLs supporting this fact",
    )
    keywords: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Distinctive salient keywords associated with this fact",
    )


class ContradictionPair(BaseModel):
    """Documented opposing or diverging factual claims expected to be identified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pair_id: str = Field(
        ..., min_length=1, description="Unique contradiction pair identifier"
    )
    topic: str = Field(..., min_length=1, description="Disputed thematic area")
    claim_a: str = Field(
        ..., min_length=1, description="First competing perspective/finding"
    )
    claim_b: str = Field(
        ..., min_length=1, description="Second competing perspective/finding"
    )
    description: str = Field(
        ..., min_length=1, description="Explanation of the factual divergence"
    )


class GoldenScenario(BaseModel):
    """Structured benchmark scenario defining gold-standard research expectations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(
        ..., min_length=1, description="Unique benchmark scenario identifier"
    )
    domain: str = Field(
        ..., min_length=1, description="Subject domain (e.g. scientific, financial)"
    )
    research_question: str = Field(
        ..., min_length=5, description="Input research question or inquiry goal"
    )
    required_topics: tuple[str, ...] = Field(
        ..., min_length=1, description="Mandatory subtopics that must be covered"
    )
    optional_topics: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Optional depth topics that do not penalize scope if omitted",
    )
    ground_truth_facts: tuple[GroundTruthFact, ...] = Field(
        ..., min_length=1, description="Canonical facts expected in the output"
    )
    expected_citations: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Expected authoritative citation sources/keys",
    )
    contradiction_pairs: tuple[ContradictionPair, ...] = Field(
        default_factory=tuple,
        description="Known contradictions that must be identified and analyzed",
    )
    minimum_quality_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Passing composite score threshold for this scenario",
    )


class BenchmarkResult(BaseModel):
    """Itemized evaluation outcome and rubric breakdown for a single benchmark scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(..., description="Evaluated scenario identifier")
    groundedness_score: float = Field(
        ..., ge=0.0, le=1.0, description="Factual faithfulness rating [0.0 - 1.0]"
    )
    scope_score: float = Field(
        ..., ge=0.0, le=1.0, description="Inquiry coverage rating [0.0 - 1.0]"
    )
    neutrality_score: float = Field(
        ..., ge=0.0, le=1.0, description="Contradiction & neutrality rating [0.0 - 1.0]"
    )
    citation_precision: float = Field(
        ..., ge=0.0, le=1.0, description="Valid citation precision [0.0 - 1.0]"
    )
    citation_recall: float = Field(
        ..., ge=0.0, le=1.0, description="Required citation recall [0.0 - 1.0]"
    )
    contradiction_precision: float = Field(
        ..., ge=0.0, le=1.0, description="Valid contradiction precision [0.0 - 1.0]"
    )
    contradiction_recall: float = Field(
        ..., ge=0.0, le=1.0, description="Required contradiction recall [0.0 - 1.0]"
    )
    composite_score: float = Field(
        ..., ge=0.0, le=1.0, description="Weighted composite score [0.0 - 1.0]"
    )
    passed: bool = Field(..., description="Whether composite_score >= threshold")
    actionable_feedback: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Actionable diagnostic findings explaining score deductions",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional evaluation context"
    )


class EvaluationScorecard(BaseModel):
    """Aggregate benchmark results across an entire benchmark dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_results: tuple[BenchmarkResult, ...] = Field(
        default_factory=tuple, description="Individual scenario results"
    )
    total_scenarios: int = Field(
        default=0, ge=0, description="Total evaluated scenarios"
    )
    passed_scenarios: int = Field(
        default=0, ge=0, description="Scenarios meeting threshold"
    )
    failed_scenarios: int = Field(
        default=0, ge=0, description="Scenarios below threshold"
    )
    average_composite_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean composite score across all scenarios",
    )
    average_groundedness: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Mean groundedness score"
    )
    average_scope: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Mean scope coverage score"
    )
    average_neutrality: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Mean neutrality/contradiction score"
    )
    regression_gate_passed: bool = Field(
        default=True,
        description="True if all evaluated scenarios passed their minimum thresholds",
    )


__all__ = [
    "BenchmarkResult",
    "ContradictionPair",
    "EvaluationScorecard",
    "GoldenScenario",
    "GroundTruthFact",
]

"""Automated evaluation framework, rubric scoring engine, and golden benchmark suite."""

from app.evaluation.dataset import (
    GOLDEN_BENCHMARK_SUITE,
    SCENARIO_BIOMEDICAL_MRNA_DELIVERY,
    SCENARIO_FINANCIAL_CBDC_SETTLEMENT,
    SCENARIO_QUANTUM_ERROR_MITIGATION,
    SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT,
    get_scenario_by_id,
)
from app.evaluation.harness import (
    evaluate_dossier,
    evaluate_scenario,
    run_benchmark,
)
from app.evaluation.models import (
    BenchmarkResult,
    ContradictionPair,
    EvaluationScorecard,
    GoldenScenario,
    GroundTruthFact,
)
from app.evaluation.rubrics import (
    GROUNDEDNESS_WEIGHT,
    NEUTRALITY_WEIGHT,
    SCOPE_WEIGHT,
    calculate_citation_metrics,
    calculate_composite_score,
    calculate_groundedness,
    calculate_neutrality,
    calculate_scope,
    compute_token_overlap,
    match_claim,
    normalize_text,
    tokenize,
)

__all__ = [
    "GOLDEN_BENCHMARK_SUITE",
    "GROUNDEDNESS_WEIGHT",
    "NEUTRALITY_WEIGHT",
    "SCENARIO_BIOMEDICAL_MRNA_DELIVERY",
    "SCENARIO_FINANCIAL_CBDC_SETTLEMENT",
    "SCENARIO_QUANTUM_ERROR_MITIGATION",
    "SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT",
    "SCOPE_WEIGHT",
    "BenchmarkResult",
    "ContradictionPair",
    "EvaluationScorecard",
    "GoldenScenario",
    "GroundTruthFact",
    "calculate_citation_metrics",
    "calculate_composite_score",
    "calculate_groundedness",
    "calculate_neutrality",
    "calculate_scope",
    "compute_token_overlap",
    "evaluate_dossier",
    "evaluate_scenario",
    "get_scenario_by_id",
    "match_claim",
    "normalize_text",
    "run_benchmark",
    "tokenize",
]

"""Deterministic offline evaluation harness and benchmark regression runner."""

import contextlib
import logging
import time
from collections.abc import Callable

from app.evaluation.dataset import GOLDEN_BENCHMARK_SUITE
from app.evaluation.models import (
    BenchmarkResult,
    EvaluationScorecard,
    GoldenScenario,
)
from app.evaluation.rubrics import (
    calculate_citation_metrics,
    calculate_composite_score,
    calculate_groundedness,
    calculate_neutrality,
    calculate_scope,
)
from app.intelligence.models import ResearchDossier

logger = logging.getLogger(__name__)


def evaluate_dossier(
    dossier: ResearchDossier, scenario: GoldenScenario
) -> BenchmarkResult:
    """Evaluate a single synthesized ResearchDossier against a GoldenScenario deterministically."""
    start_time = time.perf_counter()

    all_feedback: list[str] = []

    # 1. Groundedness (40%)
    groundedness, feedback_g = calculate_groundedness(dossier, scenario)
    all_feedback.extend(feedback_g)

    # 2. Scope & Completeness (35%)
    scope, feedback_s = calculate_scope(dossier, scenario)
    all_feedback.extend(feedback_s)

    # 3. Neutrality & Contradiction Handling (25%)
    neutrality, contra_prec, contra_rec, feedback_n = calculate_neutrality(
        dossier, scenario
    )
    all_feedback.extend(feedback_n)

    # 4. Citation Precision & Recall
    cit_prec, cit_rec, feedback_c = calculate_citation_metrics(dossier, scenario)
    all_feedback.extend(feedback_c)

    # 5. Composite Score
    composite = calculate_composite_score(
        groundedness=groundedness, scope=scope, neutrality=neutrality
    )

    threshold = scenario.minimum_quality_threshold
    passed = composite >= threshold

    if not passed:
        all_feedback.insert(
            0,
            f"Composite score ({composite:.3f}) fell below scenario threshold ({threshold:.3f}).",
        )

    duration_ms = (time.perf_counter() - start_time) * 1000.0

    # Fail-safe telemetry recording
    _record_telemetry(scenario.scenario_id, composite, duration_ms, passed)

    return BenchmarkResult(
        scenario_id=scenario.scenario_id,
        groundedness_score=groundedness,
        scope_score=scope,
        neutrality_score=neutrality,
        citation_precision=cit_prec,
        citation_recall=cit_rec,
        contradiction_precision=contra_prec,
        contradiction_recall=contra_rec,
        composite_score=composite,
        passed=passed,
        actionable_feedback=tuple(all_feedback),
        metadata={
            "duration_ms": duration_ms,
            "domain": scenario.domain,
            "dossier_id": dossier.dossier_id,
        },
    )


def evaluate_scenario(
    scenario: GoldenScenario,
    dossier_provider: Callable[[GoldenScenario], ResearchDossier],
) -> BenchmarkResult:
    """Evaluate a scenario by generating a dossier via the supplied provider function."""
    dossier = dossier_provider(scenario)
    return evaluate_dossier(dossier, scenario)


def run_benchmark(
    dossiers: dict[str, ResearchDossier] | None = None,
    scenarios: tuple[GoldenScenario, ...] | None = None,
    minimum_threshold: float = 0.85,
) -> EvaluationScorecard:
    """Run full benchmark evaluation across multiple scenarios and compile a score card."""
    eval_scenarios = scenarios or GOLDEN_BENCHMARK_SUITE
    dossier_map = dossiers or {}

    results: list[BenchmarkResult] = []

    for scenario in eval_scenarios:
        dossier = dossier_map.get(scenario.scenario_id)
        if dossier is None:
            # If no dossier provided for this scenario, create an empty failure result
            result = BenchmarkResult(
                scenario_id=scenario.scenario_id,
                groundedness_score=0.0,
                scope_score=0.0,
                neutrality_score=0.0,
                citation_precision=0.0,
                citation_recall=0.0,
                contradiction_precision=0.0,
                contradiction_recall=0.0,
                composite_score=0.0,
                passed=False,
                actionable_feedback=(
                    f"No synthesized dossier provided for scenario '{scenario.scenario_id}'.",
                ),
            )
        else:
            # Override threshold if custom minimum_threshold specified
            if scenario.minimum_quality_threshold != minimum_threshold:
                scenario = scenario.model_copy(
                    update={"minimum_quality_threshold": minimum_threshold}
                )
            result = evaluate_dossier(dossier, scenario)

        results.append(result)

    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    failed_count = total - passed_count

    avg_composite = sum(r.composite_score for r in results) / max(1, total)
    avg_groundedness = sum(r.groundedness_score for r in results) / max(1, total)
    avg_scope = sum(r.scope_score for r in results) / max(1, total)
    avg_neutrality = sum(r.neutrality_score for r in results) / max(1, total)

    gate_passed = failed_count == 0

    return EvaluationScorecard(
        scenario_results=tuple(results),
        total_scenarios=total,
        passed_scenarios=passed_count,
        failed_scenarios=failed_count,
        average_composite_score=round(avg_composite, 4),
        average_groundedness=round(avg_groundedness, 4),
        average_scope=round(avg_scope, 4),
        average_neutrality=round(avg_neutrality, 4),
        regression_gate_passed=gate_passed,
    )


def _record_telemetry(
    scenario_id: str, score: float, duration_ms: float, passed: bool
) -> None:
    """Emit telemetry metrics without failing on missing or errored telemetry provider."""
    with contextlib.suppress(Exception):
        from app.observability.factory import get_metrics

        metrics = get_metrics()
        metrics.increment_counter(
            "evaluation.runs_total",
            attributes={"scenario_id": scenario_id, "passed": passed},
        )
        metrics.record_histogram(
            "evaluation.duration_ms",
            duration_ms,
            attributes={"scenario_id": scenario_id},
        )
        metrics.record_histogram(
            "evaluation.score",
            score,
            attributes={"scenario_id": scenario_id},
        )


__all__ = [
    "evaluate_dossier",
    "evaluate_scenario",
    "run_benchmark",
]

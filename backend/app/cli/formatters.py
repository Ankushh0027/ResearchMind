"""Terminal formatting utilities for human-readable and JSON CLI output."""

import json
from typing import Any


def format_json(data: Any) -> str:
    """Serialize payload to indented, human-readable JSON."""
    return json.dumps(data, indent=2, default=str)


def format_health(data: dict[str, Any]) -> str:
    """Format system health probe response."""
    status = data.get("status", "unknown").upper()
    version = data.get("version", "unknown")
    timestamp = data.get("timestamp", "unknown")
    lines = [
        "=== ResearchMind System Health ===",
        f"Status:    {status}",
        f"Version:   {version}",
        f"Timestamp: {timestamp}",
    ]
    return "\n".join(lines)


def format_run_summary(data: dict[str, Any]) -> str:
    """Format brief research run submission summary."""
    run_id = data.get("run_id", "unknown")
    status = data.get("status", "unknown")
    query = data.get("goal_query", "unknown")
    created_at = data.get("created_at", "unknown")
    lines = [
        "=== Research Run Submitted ===",
        f"Run ID:     {run_id}",
        f"Status:     {status}",
        f"Goal Query: {query}",
        f"Created At: {created_at}",
        "",
        f"To stream live execution:  researchmind stream {run_id}",
        f"To check current status:   researchmind status {run_id}",
    ]
    return "\n".join(lines)


def format_run_detail(data: dict[str, Any], show_full_report: bool = False) -> str:
    """Format comprehensive run execution details and synthesized findings."""
    run_id = data.get("run_id", "unknown")
    status = data.get("status", "unknown")
    duration = data.get("duration_seconds", 0.0)
    completed = data.get("completed_task_ids", [])
    failed = data.get("failed_task_ids", [])
    cancelled = data.get("cancelled_task_ids", [])
    tokens = data.get("total_token_usage", {})
    dossier = data.get("dossier")
    artifacts = data.get("artifacts", [])
    error = data.get("error")

    lines = [
        f"=== Research Run: {run_id} ===",
        f"Status:          {status}",
        f"Duration:        {duration:.2f}s",
        f"Completed Tasks: {len(completed)}",
        f"Failed Tasks:    {len(failed)}",
        f"Cancelled Tasks: {len(cancelled)}",
        f"Tokens Consumed: {tokens.get('total_tokens', 0):,} (prompt: {tokens.get('prompt_tokens', 0):,}, completion: {tokens.get('completion_tokens', 0):,})",
    ]

    if error:
        lines.append(f"Error:           {error}")

    if dossier:
        confidence = dossier.get("confidence_rating", 0.0)
        ver_status = dossier.get("verification_status", "UNKNOWN")
        findings = dossier.get("key_findings", [])
        citations = dossier.get("citations", [])
        contradictions = dossier.get("contradictions", [])
        evaluation = dossier.get("evaluation")

        lines.extend(
            [
                "",
                "--- Synthesized Research Deliverable ---",
                f"Verification Status: {ver_status}",
                f"Confidence Score:    {confidence:.2%}",
                f"Key Findings:        {len(findings)}",
                f"Citations Indexed:   {len(citations)}",
                f"Contradictions:      {len(contradictions)}",
            ]
        )

        if evaluation:
            score = evaluation.get("overall_score", 0.0)
            passed = evaluation.get("passed", False)
            lines.append(
                f"Evaluation Quality:  {score:.3f} ({'PASSED' if passed else 'FAILED'})"
            )

        if show_full_report and "markdown_report" in dossier:
            lines.extend(
                [
                    "",
                    "--- Markdown Report ---",
                    dossier["markdown_report"],
                ]
            )

    if artifacts:
        lines.extend(
            [
                "",
                f"--- Durable Artifacts ({len(artifacts)}) ---",
            ]
        )
        for a in artifacts:
            lines.append(
                f"- {a.get('artifact_type', 'file')}: {a.get('object_key', '')} ({a.get('size_bytes', 0):,} bytes) [ID: {a.get('artifact_id', '')}]"
            )

    return "\n".join(lines)


def format_sse_event(event_name: str, data: Any) -> str:
    """Format single SSE progress event for live streaming output."""
    if isinstance(data, dict):
        stage = data.get("stage") or data.get("status") or ""
        msg = data.get("message") or data.get("subtask_id") or ""
        return f"[{event_name}] {stage} {msg}".strip()
    return f"[{event_name}] {data}"


def format_benchmark_result(data: dict[str, Any]) -> str:
    """Format evaluation benchmark execution results."""
    scenario_count = data.get("total_scenarios", 0)
    passed_count = data.get("passed_scenarios", 0)
    avg_score = data.get("average_composite_score", 0.0)
    regression = data.get("regression_gate_passed", False)

    lines = [
        "=== Golden Evaluation Benchmark Suite ===",
        f"Scenarios Evaluated: {scenario_count}",
        f"Passed Scenarios:    {passed_count}/{scenario_count} ({passed_count / max(scenario_count, 1):.1%})",
        f"Average Score:       {avg_score:.4f}",
        f"Regression Gate:     {'PASS' if regression else 'FAIL'} (Threshold: 0.8500)",
    ]

    results = data.get("scenario_results", [])
    if results:
        lines.append("")
        lines.append("Scenario Details:")
        for sc in results:
            scenario_id = sc.get("scenario_id", "")
            score = sc.get("composite_score", 0.0)
            passed = sc.get("passed", False)
            lines.append(
                f"  - [{('PASS' if passed else 'FAIL')}] {scenario_id}: {score:.4f}"
            )

    return "\n".join(lines)


__all__ = [
    "format_benchmark_result",
    "format_health",
    "format_json",
    "format_run_detail",
    "format_run_summary",
    "format_sse_event",
]

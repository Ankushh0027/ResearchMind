"""Main CLI router and entrypoint for ResearchMind operator tools."""

import argparse
import os
import sys
from typing import Any

from app.cli.client import CLIClientError, ResearchMindClient
from app.cli.formatters import (
    format_benchmark_result,
    format_health,
    format_json,
    format_run_detail,
    format_run_summary,
    format_sse_event,
)
from app.evaluation.dataset import (
    GOLDEN_BENCHMARK_SUITE,
    create_standard_golden_dossiers,
)
from app.evaluation.harness import run_benchmark


def _create_parser() -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--url",
        default=None,
        help="Target ResearchMind API URL (or set RESEARCHMIND_API_URL, default: http://localhost:8080)",
    )
    common_parser.add_argument(
        "--api-key",
        default=None,
        help="API Key for authenticated endpoints (or set RESEARCHMIND_API_KEY)",
    )
    common_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit output in structured JSON format",
    )

    parser = argparse.ArgumentParser(
        prog="researchmind",
        description="ResearchMind — Autonomous Multi-Agent Deep Research Platform CLI",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. health
    subparsers.add_parser(
        "health",
        parents=[common_parser],
        help="Check service health and readiness status",
    )

    # 2. submit
    submit_parser = subparsers.add_parser(
        "submit",
        parents=[common_parser],
        help="Submit a new research inquiry for autonomous investigation",
    )
    submit_parser.add_argument("query", help="Primary research inquiry prompt")
    submit_parser.add_argument(
        "--tags",
        nargs="*",
        default=[],
        help="Semantic domain tags (e.g. --tags biomedical genetics)",
    )
    submit_parser.add_argument(
        "--max-subtasks",
        type=int,
        default=10,
        help="Maximum decomposed subtasks (default: 10)",
    )

    # 3. status
    status_parser = subparsers.add_parser(
        "status",
        parents=[common_parser],
        help="Fetch status, metrics, and deliverable for a research run",
    )
    status_parser.add_argument("run_id", help="Research run identifier")
    status_parser.add_argument(
        "--full",
        action="store_true",
        help="Include full markdown report in output",
    )

    # 4. stream
    stream_parser = subparsers.add_parser(
        "stream",
        parents=[common_parser],
        help="Stream live execution events (SSE) for an active run",
    )
    stream_parser.add_argument("run_id", help="Research run identifier")

    # 5. cancel
    cancel_parser = subparsers.add_parser(
        "cancel",
        parents=[common_parser],
        help="Request cancellation of an active research run",
    )
    cancel_parser.add_argument("run_id", help="Research run identifier")

    # 6. export
    export_parser = subparsers.add_parser(
        "export",
        parents=[common_parser],
        help="Download durable artifacts and reports for a run",
    )
    export_parser.add_argument("run_id", help="Research run identifier")
    export_parser.add_argument(
        "--output-dir",
        default="./artifacts",
        help="Directory to save downloaded artifacts (default: ./artifacts)",
    )

    # 7. benchmark
    bench_parser = subparsers.add_parser(
        "benchmark",
        parents=[common_parser],
        help="Execute the offline golden evaluation benchmark suite",
    )
    bench_parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Regression pass score threshold (default: 0.85)",
    )
    bench_parser.add_argument(
        "--domain",
        default=None,
        help="Filter scenarios by domain (e.g. academic, biomedical, financial, technical)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI execution entrypoint returning standard process exit code."""
    parser = _create_parser()
    args = parser.parse_args(argv)

    client = ResearchMindClient(
        base_url=args.url,
        api_key=args.api_key,
    )

    try:
        if args.command == "health":
            data = client.health()
            if args.json:
                print(format_json(data))
            else:
                print(format_health(data))
            return 0

        elif args.command == "submit":
            data = client.submit_run(
                query=args.query,
                domain_tags=args.tags,
                max_subtasks=args.max_subtasks,
            )
            if args.json:
                print(format_json(data))
            else:
                print(format_run_summary(data))
            return 0

        elif args.command == "status":
            data = client.get_run(args.run_id)
            if args.json:
                print(format_json(data))
            else:
                print(format_run_detail(data, show_full_report=args.full))
            return 0

        elif args.command == "cancel":
            data = client.cancel_run(args.run_id)
            if args.json:
                print(format_json(data))
            else:
                print(f"Run '{args.run_id}' cancelled: {data.get('message', 'OK')}")
            return 0

        elif args.command == "stream":
            for event_name, event_data in client.stream_events(args.run_id):
                if args.json:
                    print(format_json({"event": event_name, "data": event_data}))
                else:
                    print(format_sse_event(event_name, event_data))
            return 0

        elif args.command == "export":
            artifacts = client.list_artifacts(args.run_id)
            if not artifacts:
                if args.json:
                    print(format_json({"exported": [], "count": 0}))
                else:
                    print(f"No durable artifacts found for run '{args.run_id}'.")
                return 0

            os.makedirs(args.output_dir, exist_ok=True)
            exported = []
            for art in artifacts:
                art_id = art["artifact_id"]
                filename = art.get("object_key", f"{art_id}.bin").split("/")[-1]
                target_path = os.path.join(args.output_dir, filename)
                bytes_written = client.download_artifact(
                    args.run_id, art_id, target_path
                )
                exported.append(
                    {"artifact_id": art_id, "path": target_path, "bytes": bytes_written}
                )
                if not args.json:
                    print(
                        f"Downloaded: {filename} ({bytes_written:,} bytes) -> {target_path}"
                    )

            if args.json:
                print(format_json({"exported": exported, "count": len(exported)}))
            return 0

        elif args.command == "benchmark":
            scenarios = tuple(
                s
                for s in GOLDEN_BENCHMARK_SUITE
                if args.domain is None or s.domain.lower() == args.domain.lower()
            )
            dossiers = create_standard_golden_dossiers()
            bench_result = run_benchmark(
                dossiers=dossiers,
                scenarios=scenarios,
                minimum_threshold=args.threshold,
            )
            bench_dict: dict[str, Any] = bench_result.model_dump()
            if args.json:
                print(format_json(bench_dict))
            else:
                print(format_benchmark_result(bench_dict))
            return 0 if bench_result.regression_gate_passed else 2

    except CLIClientError as e:
        if args.json:
            print(
                format_json(
                    {
                        "error": e.message,
                        "error_code": e.error_code,
                        "status_code": e.status_code,
                    }
                ),
                file=sys.stderr,
            )
        else:
            print(f"Error: {e.message}", file=sys.stderr)
        return 1
    except Exception as e:
        if args.json:
            print(
                format_json({"error": str(e), "error_code": "UNEXPECTED_ERROR"}),
                file=sys.stderr,
            )
        else:
            print(f"Unexpected error: {e}", file=sys.stderr)
        return 1

    return 0


def cli() -> None:
    """Console script entrypoint exiting with process exit code."""
    sys.exit(main())


if __name__ == "__main__":
    cli()

"""Unit tests for ResearchMind operator CLI argument parsing, formatters, and client error handling."""

import json

import pytest

from app.cli.client import CLIClientError, redact_secrets
from app.cli.formatters import (
    format_benchmark_result,
    format_health,
    format_json,
    format_run_detail,
    format_run_summary,
    format_sse_event,
)
from app.cli.main import _create_parser, main


class TestCLIParser:
    """Test CLI argument parsing and validation across all subcommands."""

    def test_health_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(["health", "--url", "http://api.local:8080", "--json"])
        assert args.command == "health"
        assert args.url == "http://api.local:8080"
        assert args.json is True

    def test_submit_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(
            [
                "submit",
                "Quantum Error Mitigation",
                "--tags",
                "physics",
                "quantum",
                "--max-subtasks",
                "5",
                "--api-key",
                "test-key",
            ]
        )
        assert args.command == "submit"
        assert args.query == "Quantum Error Mitigation"
        assert args.tags == ["physics", "quantum"]
        assert args.max_subtasks == 5
        assert args.api_key == "test-key"

    def test_status_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(["status", "run_12345", "--full", "--json"])
        assert args.command == "status"
        assert args.run_id == "run_12345"
        assert args.full is True
        assert args.json is True

    def test_stream_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(["stream", "run_12345"])
        assert args.command == "stream"
        assert args.run_id == "run_12345"

    def test_cancel_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(["cancel", "run_12345"])
        assert args.command == "cancel"
        assert args.run_id == "run_12345"

    def test_export_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(
            ["export", "run_12345", "--output-dir", "/tmp/artifacts"]
        )
        assert args.command == "export"
        assert args.run_id == "run_12345"
        assert args.output_dir == "/tmp/artifacts"

    def test_benchmark_parser(self) -> None:
        parser = _create_parser()
        args = parser.parse_args(
            ["benchmark", "--threshold", "0.90", "--domain", "biomedical", "--json"]
        )
        assert args.command == "benchmark"
        assert args.threshold == 0.90
        assert args.domain == "biomedical"
        assert args.json is True

    def test_missing_subcommand_raises(self) -> None:
        parser = _create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestSecretRedaction:
    """Test sanitization of sensitive tokens in error messages and exceptions."""

    def test_redact_secrets(self) -> None:
        raw = "Error with API key AIzaSyD4nN1x9z2b3c4d5e6f7g8h9i0j1k2l3m4 and Bearer eyJhbGciOiJIUzI1NiJ9.token"
        sanitized = redact_secrets(raw)
        assert "AIzaSy" not in sanitized
        assert "eyJhbGci" not in sanitized
        assert "[REDACTED_SECRET]" in sanitized

    def test_client_error_auto_redaction(self) -> None:
        err = CLIClientError("Failed with sk-1234567890abcdef12345678")
        assert "sk-1234567890" not in str(err)
        assert "[REDACTED_SECRET]" in str(err)


class TestCLIFormatters:
    """Test human-readable and JSON rendering functions."""

    def test_format_json(self) -> None:
        data = {"key": "value", "count": 42}
        formatted = format_json(data)
        assert json.loads(formatted) == data

    def test_format_health(self) -> None:
        data = {"status": "ok", "version": "0.1.0", "timestamp": "2026-08-29T12:00:00Z"}
        text = format_health(data)
        assert "OK" in text
        assert "0.1.0" in text

    def test_format_run_summary(self) -> None:
        data = {
            "run_id": "run_test_01",
            "status": "QUEUED",
            "goal_query": "Quantum Computing",
            "created_at": "2026-08-29T12:00:00Z",
        }
        text = format_run_summary(data)
        assert "run_test_01" in text
        assert "QUEUED" in text
        assert "Quantum Computing" in text

    def test_format_run_detail(self) -> None:
        data = {
            "run_id": "run_test_01",
            "status": "COMPLETED",
            "duration_seconds": 12.34,
            "completed_task_ids": ["t1", "t2"],
            "failed_task_ids": [],
            "cancelled_task_ids": [],
            "total_token_usage": {
                "total_tokens": 1500,
                "prompt_tokens": 1000,
                "completion_tokens": 500,
            },
            "dossier": {
                "confidence_rating": 0.95,
                "verification_status": "VERIFIED",
                "key_findings": [{"title": "Finding 1"}],
                "citations": [{"citation_key": "[CIT-1]"}],
                "contradictions": [],
                "evaluation": {"overall_score": 0.92, "passed": True},
                "markdown_report": "# Test Report",
            },
            "artifacts": [
                {
                    "artifact_type": "report",
                    "object_key": "reports/run_test_01.md",
                    "size_bytes": 1024,
                    "artifact_id": "art_1",
                }
            ],
        }
        text = format_run_detail(data, show_full_report=True)
        assert "run_test_01" in text
        assert "COMPLETED" in text
        assert "1,500" in text
        assert "VERIFIED" in text
        assert "# Test Report" in text
        assert "art_1" in text

    def test_format_sse_event(self) -> None:
        text = format_sse_event(
            "STAGE_CHANGE", {"stage": "RESEARCHING", "message": "Dispatched tasks"}
        )
        assert "[STAGE_CHANGE]" in text
        assert "RESEARCHING" in text

    def test_format_benchmark_result(self) -> None:
        data = {
            "total_scenarios": 4,
            "passed_scenarios": 4,
            "average_composite_score": 0.9781,
            "regression_gate_passed": True,
            "scenario_results": [
                {"scenario_id": "scenario_01", "composite_score": 1.0, "passed": True},
            ],
        }
        text = format_benchmark_result(data)
        assert "4/4" in text
        assert "0.9781" in text
        assert "PASS" in text


class TestCLIExecutionAndExitCodes:
    """Test deterministic CLI exit codes."""

    def test_benchmark_success_exit_code(self) -> None:
        exit_code = main(["benchmark", "--threshold", "0.80"])
        assert exit_code == 0

    def test_benchmark_failure_threshold_exit_code(self) -> None:
        exit_code = main(["benchmark", "--threshold", "0.9999"])
        # Threshold higher than technical scenario (0.9125) should fail regression gate and return exit code 2
        assert exit_code == 2

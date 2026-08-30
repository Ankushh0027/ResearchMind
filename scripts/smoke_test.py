"""Automated deployment smoke test verifying live or mock ResearchMind API & Web Workspace endpoints."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from app.api.app import create_app
from app.api.routes import set_global_service
from app.api.service import ResearchService
from app.cli.client import ResearchMindClient
from app.persistence.in_memory import (
    InMemoryCheckpointRepository,
    InMemoryRunRepository,
)
from app.storage.in_memory import InMemoryArtifactStorage


def run_smoke_tests(
    base_url: str | None = None,
    api_key: str | None = None,
    use_mock: bool = False,
) -> bool:
    """Execute end-to-end smoke verification against live target or in-memory mock."""
    print("=" * 60)
    print("ResearchMind Deployment Smoke Test Suite (Phase 7.4)")
    print("=" * 60)

    mock_app: Any = None
    if use_mock or not base_url:
        print("[MODE] Running in deterministic in-memory mock transport mode.")
        run_repo = InMemoryRunRepository()
        ckpt_repo = InMemoryCheckpointRepository()
        storage = InMemoryArtifactStorage()
        service = ResearchService(
            run_repo=run_repo,
            checkpoint_repo=ckpt_repo,
            artifact_storage=storage,
        )
        set_global_service(service)
        mock_app = create_app()
        base_url = "http://testserver"
    else:
        print(f"[MODE] Running against live deployment target: {base_url}")

    client = ResearchMindClient(
        base_url=base_url,
        api_key=api_key or "smoke-test-key",
        app=mock_app,
        timeout=15.0,
    )

    passed_checks = 0
    total_checks = 7

    # 1. Health Probe Check
    print("\n[CHECK 1/7] Probing /healthz endpoint...")
    try:
        health_data = client.health()
        assert health_data.get("status") == "ok", (
            f"Expected status 'ok', got {health_data}"
        )
        print(f"  -> PASS: System healthy (version: {health_data.get('version')})")
        passed_checks += 1
    except Exception as e:
        print(f"  -> FAIL: Health check failed: {e}")

    # 2. Frontend Workspace Root Probe
    print("\n[CHECK 2/7] Probing Web Workspace root (GET /)...")
    try:
        with client._create_http_client() as http:
            resp = http.get("/")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            assert "ResearchMind" in resp.text, "Index HTML missing title/brand"
        print("  -> PASS: Frontend Workspace shell online")
        passed_checks += 1
    except Exception as e:
        print(f"  -> FAIL: Web Workspace probe failed: {e}")

    # 3. Frontend Static Assets Probe
    print("\n[CHECK 3/7] Probing Web Workspace static CSS & JS assets...")
    try:
        with client._create_http_client() as http:
            css_resp = http.get("/css/styles.css")
            assert css_resp.status_code == 200, f"CSS failed: {css_resp.status_code}"
            js_resp = http.get("/js/app.js")
            assert js_resp.status_code == 200, f"JS failed: {js_resp.status_code}"
        print("  -> PASS: Static assets (styles.css, app.js) served successfully")
        passed_checks += 1
    except Exception as e:
        print(f"  -> FAIL: Static asset probe failed: {e}")

    # 4. Research Inquiry Submission
    print("\n[CHECK 4/7] Submitting test research inquiry...")
    run_id = None
    try:
        sub_res = client.submit_run(
            query="Evaluate post-deployment smoke test readiness and API integrity.",
            domain_tags=["smoke_test", "systems"],
            max_subtasks=3,
        )
        run_id = sub_res.get("run_id")
        assert run_id, "No run_id returned in submission response"
        print(
            f"  -> PASS: Created research run '{run_id}' (status: {sub_res.get('status')})"
        )
        passed_checks += 1
    except Exception as e:
        print(f"  -> FAIL: Submission failed: {e}")

    # 5. Status Retrieval Check
    print(f"\n[CHECK 5/7] Fetching status for run '{run_id}'...")
    if run_id:
        try:
            status_res = client.get_run(run_id)
            assert status_res.get("run_id") == run_id
            print(f"  -> PASS: Retrieved run status '{status_res.get('status')}'")
            passed_checks += 1
        except Exception as e:
            print(f"  -> FAIL: Status retrieval failed: {e}")
    else:
        print("  -> SKIP: Run submission failed earlier")

    # 6. SSE Stream Check
    print(f"\n[CHECK 6/7] Probing Server-Sent Events stream for run '{run_id}'...")
    if run_id:
        try:
            events_received = 0
            for _event_name, _event_data in client.stream_events(run_id):
                events_received += 1
                if events_received >= 1:
                    break
            print(
                f"  -> PASS: SSE stream connected and yielded {events_received} event(s)"
            )
            passed_checks += 1
        except Exception as e:
            print(f"  -> FAIL: SSE stream failed: {e}")
    else:
        print("  -> SKIP: Run submission failed earlier")

    # 7. Artifact Listing Check
    print(f"\n[CHECK 7/7] Listing durable artifacts for run '{run_id}'...")
    if run_id:
        try:
            artifacts = client.list_artifacts(run_id)
            assert isinstance(artifacts, list)
            print(f"  -> PASS: Retrieved {len(artifacts)} artifact reference(s)")
            passed_checks += 1
        except Exception as e:
            print(f"  -> FAIL: Artifact list check failed: {e}")
    else:
        print("  -> SKIP: Run submission failed earlier")

    # Summary
    print("\n" + "=" * 60)
    print(f"Smoke Test Summary: {passed_checks}/{total_checks} checks passed")
    print("=" * 60)

    return passed_checks == total_checks


def main() -> None:
    parser = argparse.ArgumentParser(description="ResearchMind Smoke Test Runner")
    parser.add_argument("--url", default=None, help="Target API URL")
    parser.add_argument("--api-key", default=None, help="API Key for target")
    parser.add_argument(
        "--mock", action="store_true", help="Run with in-memory mock transport"
    )

    args = parser.parse_args()
    success = run_smoke_tests(
        base_url=args.url,
        api_key=args.api_key,
        use_mock=args.mock,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

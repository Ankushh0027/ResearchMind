"""Unit tests for Phase 7.3 frontend asset integrity and contracts."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import AppSettings


def test_frontend_directory_and_assets_exist() -> None:
    """Verify that all Phase 7.3 frontend files and components exist on disk."""
    workspace_root = Path(__file__).resolve().parents[3]
    frontend_dir = workspace_root / "frontend"
    if not frontend_dir.exists():
        frontend_dir = Path("frontend").resolve()
    assert frontend_dir.exists(), f"Missing directory: {frontend_dir}"

    required_files = [
        "index.html",
        "css/styles.css",
        "js/app.js",
        "js/api.js",
        "js/state.js",
        "js/components/header.js",
        "js/components/inquiry_form.js",
        "js/components/agent_dag.js",
        "js/components/event_log.js",
        "js/components/diagnostics.js",
        "js/components/dossier_viewer.js",
        "js/components/artifact_explorer.js",
    ]

    for rel_path in required_files:
        file_path = frontend_dir / rel_path
        assert file_path.exists(), f"Missing required frontend asset: {rel_path}"
        assert file_path.stat().st_size > 0, f"Frontend asset is empty: {rel_path}"


def test_settings_serve_frontend_default_is_true() -> None:
    """Verify that serve_frontend setting defaults to True."""
    settings = AppSettings()
    assert settings.serve_frontend is True

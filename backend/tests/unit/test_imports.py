"""Unit tests verifying project imports and package structure."""

import importlib

import pytest

MODULES_TO_TEST = [
    "app",
    "app.agents",
    "app.agents.planner",
    "app.agents.researcher",
    "app.agents.analyst",
    "app.agents.verifier",
    "app.agents.evaluator",
    "app.agents.reporter",
    "app.orchestration",
    "app.tasks",
    "app.rag",
    "app.tools",
    "app.memory",
    "app.state",
    "app.evaluation",
    "app.security",
    "app.api",
    "app.config",
    "app.common",
]


@pytest.mark.parametrize("module_name", MODULES_TO_TEST)
def test_module_import(module_name: str) -> None:
    """Verify that every package module can be successfully imported."""
    module = importlib.import_module(module_name)
    assert module is not None

"""ResearchMind CLI package for operator and development workflows."""

from app.cli.client import CLIClientError, ResearchMindClient
from app.cli.main import cli, main

__all__ = [
    "CLIClientError",
    "ResearchMindClient",
    "cli",
    "main",
]

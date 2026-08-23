"""Verifier agent package responsible for validating claims against evidence and detecting conflicts."""

from app.agents.verifier.worker import (
    SUPPORTED_VERIFIER_TASK_TYPES,
    VerifierWorker,
)

__all__ = ["VerifierWorker", "SUPPORTED_VERIFIER_TASK_TYPES"]

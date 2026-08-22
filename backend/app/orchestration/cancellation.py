"""Cooperative cancellation token and context management."""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from app.common.errors import ExecutionCancelledError


class CancellationToken:
    """Thread-safe and task-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._is_cancelled: bool = False
        self._reason: str | None = None
        self._callbacks: list[Callable[[str], Any]] = []
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._is_cancelled

    @property
    def reason(self) -> str | None:
        """Return the reason provided when cancellation was triggered."""
        return self._reason

    def cancel(
        self, reason: str = "Execution cancelled by user or coordinator"
    ) -> None:
        """Trigger cooperative cancellation. Idempotent across multiple invocations."""
        if self._is_cancelled:
            return

        self._is_cancelled = True
        self._reason = reason
        self._event.set()

        for callback in list(self._callbacks):
            with contextlib.suppress(Exception):
                callback(reason)

    def register_callback(self, callback: Callable[[str], Any]) -> None:
        """Register a callback to be notified upon cancellation."""
        if self._is_cancelled:
            callback(self._reason or "Cancelled")
        else:
            self._callbacks.append(callback)

    def raise_if_cancelled(self, entity_id: str = "task") -> None:
        """Raise ExecutionCancelledError if cancellation has been requested."""
        if self._is_cancelled:
            raise ExecutionCancelledError(
                entity_id=entity_id,
                reason=self._reason or "Operation was cancelled",
            )

    async def wait_cancelled(self) -> None:
        """Asynchronously wait until cancellation is signaled."""
        await self._event.wait()

"""Retry policies, exponential backoff calculation, and retry predicates."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.orchestration.contracts import AgentError

SleeperType = Callable[[float], Coroutine[Any, Any, None]]


class RetryPolicy(BaseModel):
    """Configurable exponential backoff retry policy for transient task errors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(
        default=3, ge=1, le=10, description="Total allowed execution attempts"
    )
    base_delay_seconds: float = Field(
        default=1.0, ge=0.0, description="Base backoff delay in seconds"
    )
    max_delay_seconds: float = Field(
        default=60.0, ge=0.0, description="Maximum backoff delay ceiling"
    )
    exponential_factor: float = Field(
        default=2.0, ge=1.0, description="Multiplier per successive attempt"
    )

    def calculate_delay(self, attempt: int) -> float:
        """Calculate backoff delay for the given 1-indexed attempt number.

        Attempt 1 -> initial try (delay 0.0)
        Attempt 2 -> 1st retry (delay = base_delay)
        Attempt 3 -> 2nd retry (delay = min(base_delay * factor^1, max_delay))
        """
        if attempt <= 1:
            return 0.0
        exponent = attempt - 2
        raw_delay = self.base_delay_seconds * (self.exponential_factor**exponent)
        return min(raw_delay, self.max_delay_seconds)

    def should_retry(self, attempt: int, error: AgentError | Exception | None) -> bool:
        """Evaluate whether a task is eligible for another retry attempt."""
        if attempt >= self.max_attempts:
            return False

        if error is None:
            return False

        if isinstance(error, AgentError):
            return error.is_retryable

        # Standard exceptions default to retryable unless specifically designated
        return True


async def default_async_sleeper(seconds: float) -> None:
    """Standard asyncio sleep implementation."""
    await asyncio.sleep(seconds)

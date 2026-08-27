"""Google Gemini LLM adapter implementing LLMClientProtocol with structured generation and resilient retry handling."""

import asyncio
import logging
import random
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.adapters.llm.base import (
    LLMClientProtocol,
    LLMRequest,
    LLMResponse,
)
from app.common.errors import ResearchMindError

logger = logging.getLogger("researchmind.adapters.llm.gemini")

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


def _is_retryable_error(exc: Exception) -> bool:
    """Determine whether an exception represents a transient, retryable failure."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True

    status_code = getattr(exc, "status_code", getattr(exc, "code", None))
    if status_code in (400, 401, 403, 404):
        return False
    if status_code in (429, 500, 502, 503, 504):
        return True

    err_str = str(exc).upper()
    non_retryable_markers = (
        "400",
        "401",
        "403",
        "404",
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "API_KEY_INVALID",
        "API KEY NOT VALID",
    )
    if any(marker in err_str for marker in non_retryable_markers):
        return False

    retryable_markers = (
        "429",
        "RESOURCE_EXHAUSTED",
        "QUOTA",
        "RATE_LIMIT",
        "500",
        "502",
        "503",
        "504",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "INTERNAL",
        "SERVER_ERROR",
        "CONNECTION_RESET",
        "TIMEOUT",
        "TEMPORARY",
    )
    return any(marker in err_str for marker in retryable_markers)


def _mask_api_key(api_key: str | None) -> str:
    """Return a masked representation of an API key for safe logging."""
    if not api_key:
        return "<none>"
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


class GeminiLLMClient(LLMClientProtocol):
    """Production-grade Google Gemini Large Language Model client adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-pro",
        fast_model_name: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
        request_timeout_seconds: float = 60.0,
        max_retries: int = 3,
        initial_retry_delay_seconds: float = 1.0,
        max_retry_delay_seconds: float = 10.0,
        client: Any = None,
    ) -> None:
        self.api_key = api_key or ""
        self.model_name = model_name
        self.fast_model_name = fast_model_name
        self.temperature = max(0.0, min(2.0, temperature))
        self.max_output_tokens = max(1, max_output_tokens)
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.max_retries = max(0, max_retries)
        self.initial_retry_delay_seconds = max(0.01, initial_retry_delay_seconds)
        self.max_retry_delay_seconds = max(
            self.initial_retry_delay_seconds, max_retry_delay_seconds
        )
        self._client = client

    def _get_client(self) -> Any:
        """Resolve or lazily initialize the Google GenAI SDK client."""
        if self._client is not None:
            return self._client

        if not self.api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY is required for GeminiLLMClient when no client is injected."
            )

        try:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
            return self._client
        except ImportError as e:
            raise RuntimeError(
                "google-genai is required for GeminiLLMClient. "
                "Install with: pip install google-genai"
            ) from e

    async def _execute_with_retry(
        self,
        operation_name: str,
        func: Callable[[], Coroutine[Any, Any, R]],
    ) -> R:
        """Execute an asynchronous operation with timeout, bounded exponential backoff, and jitter."""
        attempt = 0
        while True:
            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    return await func()
            except asyncio.CancelledError:
                logger.info(
                    "Operation '%s' was cancelled during execution.", operation_name
                )
                raise
            except Exception as exc:
                if isinstance(exc, (ValidationError, ValueError)) and not isinstance(
                    exc, ResearchMindError
                ):
                    # Schema or input validation failures should never retry
                    raise

                if not _is_retryable_error(exc) or attempt >= self.max_retries:
                    logger.error(
                        "Operation '%s' failed (attempt %d/%d, retryable=%s): %s",
                        operation_name,
                        attempt + 1,
                        self.max_retries + 1,
                        _is_retryable_error(exc),
                        type(exc).__name__,
                    )
                    raise

                base_delay = min(
                    self.max_retry_delay_seconds,
                    self.initial_retry_delay_seconds * (2**attempt),
                )
                jitter = random.uniform(0.8, 1.2)
                delay = base_delay * jitter

                logger.warning(
                    "Operation '%s' encountered transient error on attempt %d/%d: %s. Retrying in %.2fs...",
                    operation_name,
                    attempt + 1,
                    self.max_retries,
                    type(exc).__name__,
                    delay,
                )

                await asyncio.sleep(delay)
                attempt += 1

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        """Generate unstructured text or tool-call completion via Gemini API."""
        client = self._get_client()
        temp = (
            request.temperature if request.temperature is not None else self.temperature
        )
        max_tokens = request.max_tokens or self.max_output_tokens
        model = self.model_name

        async def _call() -> Any:
            # Check for modern Google GenAI Client .aio.models.generate_content
            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                config: Any
                try:
                    from google.genai import types

                    config = types.GenerateContentConfig(
                        temperature=temp,
                        max_output_tokens=max_tokens,
                        system_instruction=request.system_prompt
                        if request.system_prompt
                        else None,
                    )
                except (ImportError, AttributeError):
                    config = {
                        "temperature": temp,
                        "max_output_tokens": max_tokens,
                        "system_instruction": request.system_prompt,
                    }
                return await client.aio.models.generate_content(
                    model=model,
                    contents=request.user_prompt,
                    config=config,
                )

            # Fallback for injected or mock client interfaces
            if hasattr(client, "generate_content"):
                func = client.generate_content
                kwargs = {
                    "model": model,
                    "contents": request.user_prompt,
                    "system_prompt": request.system_prompt,
                    "temperature": temp,
                    "max_tokens": max_tokens,
                }
                if asyncio.iscoroutinefunction(func):
                    return await func(**kwargs)
                return await asyncio.to_thread(func, **kwargs)

            if hasattr(client, "generate_text"):
                func = client.generate_text
                if asyncio.iscoroutinefunction(func):
                    return await func(request)
                return await asyncio.to_thread(func, request)

            raise RuntimeError(
                f"Injected client {type(client).__name__} does not support text generation."
            )

        raw_response = await self._execute_with_retry("generate_text", _call)

        # If client directly returned LLMResponse
        if isinstance(raw_response, LLMResponse):
            return raw_response

        content = getattr(raw_response, "text", "") or ""
        usage = getattr(raw_response, "usage_metadata", None)
        prompt_tokens = (
            getattr(usage, "prompt_token_count", 0) if usage is not None else 0
        )
        completion_tokens = (
            getattr(usage, "candidates_token_count", 0) if usage is not None else 0
        )
        total_tokens = (
            getattr(usage, "total_token_count", prompt_tokens + completion_tokens)
            if usage is not None
            else prompt_tokens + completion_tokens
        )

        return LLMResponse(
            content=content,
            structured_output=None,
            tool_calls=(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_name=self.model_name,
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T],
        temperature: float = 0.0,
    ) -> T:
        """Generate structured response guaranteed to validate into the specified Pydantic schema."""
        client = self._get_client()
        model = self.model_name

        async def _call() -> Any:
            # Check for modern Google GenAI SDK .aio.models.generate_content
            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                config: Any
                try:
                    from google.genai import types

                    config = types.GenerateContentConfig(
                        temperature=temperature,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        system_instruction=system_prompt if system_prompt else None,
                    )
                except (ImportError, AttributeError):
                    config = {
                        "temperature": temperature,
                        "response_mime_type": "application/json",
                        "response_schema": response_schema,
                        "system_instruction": system_prompt,
                    }
                return await client.aio.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config,
                )

            # Fallback for injected / mock clients
            if hasattr(client, "generate_structured"):
                func = client.generate_structured
                if asyncio.iscoroutinefunction(func):
                    return await func(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_schema=response_schema,
                        temperature=temperature,
                    )
                return await asyncio.to_thread(
                    func,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_schema=response_schema,
                    temperature=temperature,
                )

            if hasattr(client, "generate_content"):
                func = client.generate_content
                kwargs = {
                    "model": model,
                    "contents": user_prompt,
                    "system_prompt": system_prompt,
                    "response_schema": response_schema,
                    "temperature": temperature,
                }
                if asyncio.iscoroutinefunction(func):
                    return await func(**kwargs)
                return await asyncio.to_thread(func, **kwargs)

            raise RuntimeError(
                f"Injected client {type(client).__name__} does not support structured generation."
            )

        raw_response = await self._execute_with_retry("generate_structured", _call)

        # 1. If response is already an instance of response_schema
        if isinstance(raw_response, response_schema):
            return raw_response

        # 2. If response has .parsed attribute
        parsed = getattr(raw_response, "parsed", None)
        if isinstance(parsed, response_schema):
            return parsed
        if isinstance(parsed, dict):
            return response_schema.model_validate(parsed)

        # 3. If response has .text containing JSON
        text = getattr(raw_response, "text", None)
        if isinstance(text, str) and text.strip():
            try:
                return response_schema.model_validate_json(text)
            except Exception as e:
                logger.error(
                    "Failed to deserialize model JSON output into schema %s: %s",
                    response_schema.__name__,
                    e,
                )
                raise ValueError(
                    f"Model output could not be validated as {response_schema.__name__}: {e}"
                ) from e

        # 4. If raw_response is a dict
        if isinstance(raw_response, dict):
            return response_schema.model_validate(raw_response)

        raise ValueError(
            f"Unable to extract valid {response_schema.__name__} from provider response: {raw_response!r}"
        )


__all__ = [
    "GeminiLLMClient",
    "_is_retryable_error",
    "_mask_api_key",
]

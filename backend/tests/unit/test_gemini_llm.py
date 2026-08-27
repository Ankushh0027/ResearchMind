"""Comprehensive unit tests for Google Gemini LLM adapter."""

import asyncio
import builtins
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from app.adapters.llm.base import LLMClientProtocol, LLMRequest, LLMResponse
from app.adapters.llm.gemini import (
    GeminiLLMClient,
    _is_retryable_error,
    _mask_api_key,
)


class SampleDecomposition(BaseModel):
    """Sample target Pydantic schema for structured generation testing."""

    rationale: str = Field(..., min_length=1)
    task_count: int = Field(..., ge=1)
    tags: list[str] = Field(default_factory=list)


class FakeUsageMetadata:
    def __init__(
        self,
        prompt_token_count: int = 15,
        candidates_token_count: int = 35,
        total_token_count: int = 50,
    ) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count
        self.total_token_count = total_token_count


class FakeGenerateContentResponse:
    def __init__(
        self,
        text: str = "Synthesized analysis.",
        parsed: Any = None,
        usage_metadata: FakeUsageMetadata | None = None,
    ) -> None:
        self.text = text
        self.parsed = parsed
        self.usage_metadata = usage_metadata or FakeUsageMetadata()


class FakeAsyncModels:
    def __init__(self) -> None:
        self.recorded_calls: list[dict[str, Any]] = []
        self.side_effects: list[Any] = []
        self.call_count = 0

    async def generate_content(
        self, model: str, contents: Any, config: Any = None
    ) -> Any:
        self.call_count += 1
        self.recorded_calls.append(
            {"model": model, "contents": contents, "config": config}
        )
        if self.side_effects:
            effect = self.side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            if callable(effect):
                return effect()
            return effect
        return FakeGenerateContentResponse()


class FakeAsyncGenAI:
    def __init__(self) -> None:
        self.models = FakeAsyncModels()


class FakeGenAIClient:
    def __init__(self) -> None:
        self.aio = FakeAsyncGenAI()


def test_gemini_llm_satisfies_protocol() -> None:
    """Verify GeminiLLMClient satisfies LLMClientProtocol."""
    client = FakeGenAIClient()
    adapter = GeminiLLMClient(api_key="fake-key", client=client)
    assert isinstance(adapter, LLMClientProtocol)


@pytest.mark.asyncio
async def test_gemini_llm_successful_text_generation() -> None:
    """Test text generation with custom prompt, temperature, and tokens."""
    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(
            text="Quantum computing research findings.",
            usage_metadata=FakeUsageMetadata(20, 60, 80),
        )
    ]

    adapter = GeminiLLMClient(
        api_key="fake-secret-key-12345",
        model_name="gemini-2.5-pro",
        client=client,
    )

    request = LLMRequest(
        system_prompt="You are a research scientist.",
        user_prompt="Summarize quantum error correction.",
        temperature=0.4,
        max_tokens=1024,
    )

    response = await adapter.generate_text(request)

    assert isinstance(response, LLMResponse)
    assert response.content == "Quantum computing research findings."
    assert response.prompt_tokens == 20
    assert response.completion_tokens == 60
    assert response.total_tokens == 80
    assert response.model_name == "gemini-2.5-pro"
    assert len(client.aio.models.recorded_calls) == 1


@pytest.mark.asyncio
async def test_gemini_llm_text_generation_without_usage_metadata() -> None:
    """Test text generation when provider response has no usage metadata."""
    client = FakeGenAIClient()
    resp = FakeGenerateContentResponse(text="Simple text.")
    resp.usage_metadata = None  # type: ignore[assignment]
    client.aio.models.side_effects = [resp]

    adapter = GeminiLLMClient(api_key="fake-key", client=client)
    response = await adapter.generate_text(LLMRequest(user_prompt="Test prompt"))

    assert response.content == "Simple text."
    assert response.prompt_tokens == 0
    assert response.completion_tokens == 0
    assert response.total_tokens == 0


@pytest.mark.asyncio
async def test_gemini_llm_successful_structured_generation_json() -> None:
    """Verify structured generation validates cleanly into Pydantic schema from JSON string."""
    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(
            text='{"rationale": "Decompose into 3 quantum tasks", "task_count": 3, "tags": ["quantum", "qec"]}'
        )
    ]

    adapter = GeminiLLMClient(
        api_key="fake-secret-key-12345",
        client=client,
    )

    result = await adapter.generate_structured(
        system_prompt="Decompose inquiry",
        user_prompt="Quantum error correction",
        response_schema=SampleDecomposition,
        temperature=0.0,
    )

    assert isinstance(result, SampleDecomposition)
    assert result.rationale == "Decompose into 3 quantum tasks"
    assert result.task_count == 3
    assert result.tags == ["quantum", "qec"]


@pytest.mark.asyncio
async def test_gemini_llm_successful_structured_generation_parsed() -> None:
    """Verify structured generation with parsed SDK object or dictionary."""
    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(
            text="",
            parsed={
                "rationale": "Parsed from SDK dictionary",
                "task_count": 2,
                "tags": ["parsed"],
            },
        )
    ]

    adapter = GeminiLLMClient(
        api_key="fake-secret-key-12345",
        client=client,
    )

    result = await adapter.generate_structured(
        system_prompt="Analyze claims",
        user_prompt="Evidence summary",
        response_schema=SampleDecomposition,
    )

    assert isinstance(result, SampleDecomposition)
    assert result.rationale == "Parsed from SDK dictionary"
    assert result.task_count == 2


@pytest.mark.asyncio
async def test_gemini_llm_structured_generation_direct_instance() -> None:
    """Verify structured generation when provider directly returns schema instance."""
    client = FakeGenAIClient()
    expected = SampleDecomposition(
        rationale="Direct instance", task_count=1, tags=["direct"]
    )
    client.aio.models.side_effects = [expected]

    adapter = GeminiLLMClient(api_key="fake-key", client=client)
    result = await adapter.generate_structured(
        system_prompt="System",
        user_prompt="User",
        response_schema=SampleDecomposition,
    )
    assert result == expected


@pytest.mark.asyncio
async def test_gemini_llm_structured_generation_malformed_json_raises_value_error() -> (
    None
):
    """Verify ValueError is raised with clear context when model returns invalid JSON."""
    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(text="This is not valid json at all")
    ]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=1,
    )

    with pytest.raises(ValueError, match="could not be validated"):
        await adapter.generate_structured(
            system_prompt="Decompose",
            user_prompt="Quantum query",
            response_schema=SampleDecomposition,
        )


@pytest.mark.asyncio
async def test_gemini_llm_structured_generation_schema_mismatch_raises_value_error() -> (
    None
):
    """Verify ValueError is raised when JSON missing required schema fields."""
    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(text='{"wrong_field": 123}')
    ]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=1,
    )

    with pytest.raises(ValueError, match="could not be validated"):
        await adapter.generate_structured(
            system_prompt="Decompose",
            user_prompt="Quantum query",
            response_schema=SampleDecomposition,
        )


def test_gemini_llm_missing_api_key_error() -> None:
    """Verify ValueError if GEMINI_API_KEY is missing and no client injected."""
    adapter = GeminiLLMClient(api_key="")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        adapter._get_client()


def test_gemini_llm_missing_dependency_error() -> None:
    """Verify clear RuntimeError if google-genai is uninstalled."""
    orig_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        fromlist = args[2] if len(args) >= 3 else kwargs.get("fromlist", ())
        if "genai" in name or (fromlist and any("genai" in str(x) for x in fromlist)):
            raise ImportError("Mocked missing genai SDK")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        adapter = GeminiLLMClient(api_key="some-key")
        with pytest.raises(RuntimeError, match="google-genai is required"):
            adapter._get_client()


@pytest.mark.asyncio
async def test_gemini_llm_retry_on_429_rate_limit() -> None:
    """Verify exponential retry when encountering HTTP 429 rate limit."""
    client = FakeGenAIClient()

    class RateLimitError(Exception):
        def __init__(self) -> None:
            super().__init__("429 Resource has been exhausted (e.g. check quota).")
            self.status_code = 429

    client.aio.models.side_effects = [
        RateLimitError(),
        FakeGenerateContentResponse(text="Success after 429 retry."),
    ]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=3,
        initial_retry_delay_seconds=0.01,
        max_retry_delay_seconds=0.05,
    )

    response = await adapter.generate_text(LLMRequest(user_prompt="Test retry query"))
    assert response.content == "Success after 429 retry."
    assert client.aio.models.call_count == 2


@pytest.mark.asyncio
async def test_gemini_llm_retry_on_500_503_server_errors() -> None:
    """Verify exponential retry on 500 and 503 internal server errors."""
    client = FakeGenAIClient()

    class ServerError500(Exception):
        def __init__(self) -> None:
            super().__init__("500 Internal server error")
            self.status_code = 500

    class ServiceUnavailable503(Exception):
        def __init__(self) -> None:
            super().__init__("503 Service Unavailable")
            self.status_code = 503

    client.aio.models.side_effects = [
        ServerError500(),
        ServiceUnavailable503(),
        FakeGenerateContentResponse(text="Success on attempt 3."),
    ]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=3,
        initial_retry_delay_seconds=0.01,
        max_retry_delay_seconds=0.05,
    )

    response = await adapter.generate_text(
        LLMRequest(user_prompt="Test multi-error retry")
    )
    assert response.content == "Success on attempt 3."
    assert client.aio.models.call_count == 3


@pytest.mark.asyncio
async def test_gemini_llm_retry_on_timeout_error() -> None:
    """Verify retry on TimeoutError / asyncio.TimeoutError."""
    client = FakeGenAIClient()

    client.aio.models.side_effects = [
        TimeoutError("Connection timed out"),
        FakeGenerateContentResponse(text="Success after timeout."),
    ]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=2,
        initial_retry_delay_seconds=0.01,
        max_retry_delay_seconds=0.05,
    )

    response = await adapter.generate_text(LLMRequest(user_prompt="Timeout test"))
    assert response.content == "Success after timeout."
    assert client.aio.models.call_count == 2


@pytest.mark.asyncio
async def test_gemini_llm_retry_exhaustion_raises_error() -> None:
    """Verify exception is raised after retry attempts are exhausted."""
    client = FakeGenAIClient()

    class PersistentRateLimit(Exception):
        def __init__(self) -> None:
            super().__init__("429 Quota exceeded")
            self.status_code = 429

    client.aio.models.side_effects = [
        PersistentRateLimit(),
        PersistentRateLimit(),
        PersistentRateLimit(),
        PersistentRateLimit(),
    ]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=2,
        initial_retry_delay_seconds=0.01,
        max_retry_delay_seconds=0.05,
    )

    with pytest.raises(PersistentRateLimit):
        await adapter.generate_text(LLMRequest(user_prompt="Exhaustion test"))

    assert client.aio.models.call_count == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_gemini_llm_non_retryable_error_fails_immediately() -> None:
    """Verify non-retryable errors (e.g. 400 Bad Request) fail immediately without retrying."""
    client = FakeGenAIClient()

    class BadRequest400(Exception):
        def __init__(self) -> None:
            super().__init__("400 Invalid argument passed")
            self.status_code = 400

    client.aio.models.side_effects = [BadRequest400()]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=3,
        initial_retry_delay_seconds=0.01,
    )

    with pytest.raises(BadRequest400):
        await adapter.generate_text(LLMRequest(user_prompt="Invalid arg test"))

    assert client.aio.models.call_count == 1  # No retries


@pytest.mark.asyncio
async def test_gemini_llm_permanent_auth_error_fails_fast() -> None:
    """Verify HTTP 401 and 403 permanent authentication/permission errors fail immediately without retries."""
    client = FakeGenAIClient()

    class AuthError401(Exception):
        def __init__(self) -> None:
            super().__init__("401 UNAUTHENTICATED: API_KEY_INVALID")
            self.status_code = 401

    client.aio.models.side_effects = [AuthError401()]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=3,
        initial_retry_delay_seconds=0.01,
    )

    with pytest.raises(AuthError401):
        await adapter.generate_text(LLMRequest(user_prompt="Auth test"))

    assert client.aio.models.call_count == 1  # Fails fast on attempt 1


@pytest.mark.asyncio
async def test_gemini_llm_cancellation_during_retry_wait() -> None:
    """Verify that cancelling task during retry sleep cleanly cancels without hanging."""
    client = FakeGenAIClient()

    class SlowRateLimit(Exception):
        def __init__(self) -> None:
            super().__init__("429 Rate limit")
            self.status_code = 429

    client.aio.models.side_effects = [SlowRateLimit(), SlowRateLimit()]

    adapter = GeminiLLMClient(
        api_key="fake-key",
        client=client,
        max_retries=3,
        initial_retry_delay_seconds=0.01,
        max_retry_delay_seconds=0.05,
    )

    with (
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        pytest.raises(asyncio.CancelledError),
    ):
        await adapter.generate_text(LLMRequest(user_prompt="Cancellation test"))


def test_gemini_llm_mask_api_key_and_secrets() -> None:
    """Verify API key masking and that sensitive credentials never leak."""
    secret = "fake-secret-key-mock-1234567890"
    masked = _mask_api_key(secret)
    assert masked == "fake...7890"
    assert secret not in masked

    assert _mask_api_key("") == "<none>"
    assert _mask_api_key("short") == "***"

    # Verify helper error classifier
    assert _is_retryable_error(Exception("429 RESOURCE_EXHAUSTED")) is True
    assert _is_retryable_error(Exception("503 Service Unavailable")) is True
    assert _is_retryable_error(TimeoutError("Timeout")) is True
    assert _is_retryable_error(Exception("400 Bad Request")) is False
    assert _is_retryable_error(Exception("401 UNAUTHENTICATED")) is False
    assert _is_retryable_error(Exception("403 PERMISSION_DENIED")) is False

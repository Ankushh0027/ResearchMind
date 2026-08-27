"""Comprehensive unit tests for Google Gemini embedding adapter."""

import builtins
import math
from typing import Any
from unittest.mock import patch

import pytest

from app.adapters.llm.gemini_embeddings import (
    DEFAULT_GEMINI_EMBEDDING_DIMENSION,
    GeminiEmbeddingModel,
)
from app.common.errors import EvidenceValidationError
from app.rag.chunking import TextChunk
from app.rag.embeddings import EmbeddingRecord
from app.rag.protocols import EmbeddingModelProtocol


class FakeSingleEmbedding:
    def __init__(self, dimension: int = DEFAULT_GEMINI_EMBEDDING_DIMENSION) -> None:
        self.values = [0.01 * (i % 100) for i in range(dimension)]


class FakeEmbedContentResponse:
    def __init__(
        self,
        count: int = 1,
        dimension: int = DEFAULT_GEMINI_EMBEDDING_DIMENSION,
    ) -> None:
        self.embeddings = [
            FakeSingleEmbedding(dimension=dimension) for _ in range(count)
        ]


class FakeEmbeddingAsyncModels:
    def __init__(self) -> None:
        self.recorded_calls: list[dict[str, Any]] = []
        self.side_effects: list[Any] = []
        self.call_count = 0

    async def embed_content(self, model: str, contents: Any, config: Any = None) -> Any:
        self.call_count += 1
        self.recorded_calls.append(
            {"model": model, "contents": contents, "config": config}
        )
        if self.side_effects:
            effect = self.side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        count = len(contents) if isinstance(contents, list) else 1
        return FakeEmbedContentResponse(count=count)


class FakeEmbeddingAsyncGenAI:
    def __init__(self) -> None:
        self.models = FakeEmbeddingAsyncModels()


class FakeEmbeddingGenAIClient:
    def __init__(self) -> None:
        self.aio = FakeEmbeddingAsyncGenAI()


def test_gemini_embedding_satisfies_protocol() -> None:
    """Verify GeminiEmbeddingModel satisfies EmbeddingModelProtocol."""
    client = FakeEmbeddingGenAIClient()
    adapter = GeminiEmbeddingModel(api_key="fake-key", client=client)
    assert isinstance(adapter, EmbeddingModelProtocol)
    assert adapter.dimension == DEFAULT_GEMINI_EMBEDDING_DIMENSION


@pytest.mark.asyncio
async def test_gemini_embedding_single_text() -> None:
    """Verify single text embedding generation."""
    client = FakeEmbeddingGenAIClient()
    adapter = GeminiEmbeddingModel(
        api_key="fake-api-key",
        model_name="text-embedding-004",
        dimension=DEFAULT_GEMINI_EMBEDDING_DIMENSION,
        client=client,
    )

    vec = await adapter.embed_text("Quantum entanglement research overview.")
    assert isinstance(vec, tuple)
    assert len(vec) == DEFAULT_GEMINI_EMBEDDING_DIMENSION
    assert all(isinstance(x, float) for x in vec)
    assert client.aio.models.call_count == 1


@pytest.mark.asyncio
async def test_gemini_embedding_batch_texts() -> None:
    """Verify batch text embedding generation."""
    client = FakeEmbeddingGenAIClient()
    adapter = GeminiEmbeddingModel(
        api_key="fake-api-key",
        client=client,
    )

    texts = [
        "Quantum superposition principles.",
        "Error correcting topological surface codes.",
        "Decoherence suppression algorithms.",
    ]
    vectors = await adapter.embed_batch(texts)

    assert len(vectors) == 3
    for v in vectors:
        assert isinstance(v, tuple)
        assert len(v) == DEFAULT_GEMINI_EMBEDDING_DIMENSION

    # Empty batch returns empty list immediately
    empty_vecs = await adapter.embed_batch([])
    assert empty_vecs == []


@pytest.mark.asyncio
async def test_gemini_embedding_chunk_to_record() -> None:
    """Verify embed_chunk creates an immutable EmbeddingRecord from a TextChunk."""
    client = FakeEmbeddingGenAIClient()
    adapter = GeminiEmbeddingModel(
        api_key="fake-api-key",
        model_name="text-embedding-004",
        client=client,
    )

    chunk = TextChunk(
        chunk_id="chk_12345",
        evidence_id="ev_67890",
        run_id="run_test_01",
        text="Empirical results demonstrate a 4x reduction in logical error rates.",
        chunk_index=0,
        total_chunks=1,
        start_offset=0,
        end_offset=68,
    )

    record = await adapter.embed_chunk(chunk)
    assert isinstance(record, EmbeddingRecord)
    assert record.chunk_id == "chk_12345"
    assert record.evidence_id == "ev_67890"
    assert record.run_id == "run_test_01"
    assert record.dimension == DEFAULT_GEMINI_EMBEDDING_DIMENSION
    assert len(record.vector) == DEFAULT_GEMINI_EMBEDDING_DIMENSION
    assert record.model_name == "text-embedding-004"


@pytest.mark.asyncio
async def test_gemini_embedding_dimension_mismatch_raises_error() -> None:
    """Verify EvidenceValidationError when provider returns unexpected vector dimension."""
    client = FakeEmbeddingGenAIClient()
    # Provider returns dimension 128 instead of expected 768
    client.aio.models.side_effects = [FakeEmbedContentResponse(count=1, dimension=128)]

    adapter = GeminiEmbeddingModel(
        api_key="fake-key",
        dimension=768,
        client=client,
    )

    with pytest.raises(EvidenceValidationError, match="Vector dimension mismatch"):
        await adapter.embed_text("Test vector dimensionality mismatch")


@pytest.mark.asyncio
async def test_gemini_embedding_nan_inf_validation_raises_error() -> None:
    """Verify EvidenceValidationError when provider returns NaN or Inf values."""
    client = FakeEmbeddingGenAIClient()
    bad_resp = FakeEmbedContentResponse(count=1, dimension=768)
    bad_resp.embeddings[0].values[0] = float("nan")
    client.aio.models.side_effects = [bad_resp]

    adapter = GeminiEmbeddingModel(api_key="fake-key", client=client)

    with pytest.raises(EvidenceValidationError, match="is NaN"):
        await adapter.embed_text("Test NaN vector")

    # Test Inf vector
    bad_resp2 = FakeEmbedContentResponse(count=1, dimension=768)
    bad_resp2.embeddings[0].values[0] = math.inf
    client.aio.models.side_effects = [bad_resp2]

    with pytest.raises(EvidenceValidationError, match="is infinite"):
        await adapter.embed_text("Test Inf vector")


def test_gemini_embedding_missing_api_key_error() -> None:
    """Verify ValueError when api_key is missing and no client is injected."""
    adapter = GeminiEmbeddingModel(api_key="")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        adapter._get_client()


def test_gemini_embedding_missing_dependency_error() -> None:
    """Verify clear RuntimeError when google-genai is not installed."""
    orig_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        fromlist = args[2] if len(args) >= 3 else kwargs.get("fromlist", ())
        if "genai" in name or (fromlist and any("genai" in str(x) for x in fromlist)):
            raise ImportError("Mocked missing genai")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        adapter = GeminiEmbeddingModel(api_key="some-key")
        with pytest.raises(RuntimeError, match="google-genai is required"):
            adapter._get_client()


@pytest.mark.asyncio
async def test_gemini_embedding_retry_on_transient_error() -> None:
    """Verify exponential retry when encountering 429 or 503 during embedding."""
    client = FakeEmbeddingGenAIClient()

    class QuotaError(Exception):
        def __init__(self) -> None:
            super().__init__("429 Resource has been exhausted")
            self.status_code = 429

    client.aio.models.side_effects = [
        QuotaError(),
        FakeEmbedContentResponse(count=1),
    ]

    adapter = GeminiEmbeddingModel(
        api_key="fake-key",
        client=client,
        max_retries=3,
        initial_retry_delay_seconds=0.01,
        max_retry_delay_seconds=0.05,
    )

    vec = await adapter.embed_text("Retried embedding text")
    assert len(vec) == DEFAULT_GEMINI_EMBEDDING_DIMENSION
    assert client.aio.models.call_count == 2


@pytest.mark.asyncio
async def test_gemini_embedding_retry_on_timeout_error() -> None:
    """Verify retry when encountering TimeoutError."""
    client = FakeEmbeddingGenAIClient()
    client.aio.models.side_effects = [
        TimeoutError("Embedding timed out"),
        FakeEmbedContentResponse(count=1),
    ]

    adapter = GeminiEmbeddingModel(
        api_key="fake-key",
        client=client,
        max_retries=2,
        initial_retry_delay_seconds=0.01,
    )

    vec = await adapter.embed_text("Timeout retry text")
    assert len(vec) == DEFAULT_GEMINI_EMBEDDING_DIMENSION
    assert client.aio.models.call_count == 2


@pytest.mark.asyncio
async def test_gemini_embedding_permanent_error_fails_fast() -> None:
    """Verify HTTP 401 permanent authentication error fails fast without retrying."""
    client = FakeEmbeddingGenAIClient()

    class AuthError(Exception):
        def __init__(self) -> None:
            super().__init__("401 UNAUTHENTICATED")
            self.status_code = 401

    client.aio.models.side_effects = [AuthError()]

    adapter = GeminiEmbeddingModel(
        api_key="fake-key",
        client=client,
        max_retries=3,
    )

    with pytest.raises(AuthError):
        await adapter.embed_text("Auth test")

    assert client.aio.models.call_count == 1


@pytest.mark.asyncio
async def test_gemini_embedding_input_validation() -> None:
    """Verify strict input validation for empty texts and invalid inputs."""
    adapter = GeminiEmbeddingModel(
        api_key="fake-key", client=FakeEmbeddingGenAIClient()
    )

    with pytest.raises(EvidenceValidationError, match="empty or whitespace"):
        await adapter.embed_text("   ")

    with pytest.raises(TypeError, match="cannot be None"):
        await adapter.embed_text(None)  # type: ignore[arg-type]

    with pytest.raises(EvidenceValidationError, match="non-empty string"):
        await adapter.embed_batch(["valid", ""])

    with pytest.raises(EvidenceValidationError, match="positive integer"):
        GeminiEmbeddingModel(api_key="key", dimension=-1)

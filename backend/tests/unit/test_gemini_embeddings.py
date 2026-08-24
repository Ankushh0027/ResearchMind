"""Comprehensive unit tests for Google Gemini embedding adapter."""

import builtins
from typing import Any
from unittest.mock import patch

import pytest

from app.common.errors import EvidenceValidationError
from app.rag.chunking import TextChunk
from app.rag.embeddings import EmbeddingRecord
from app.rag.gemini import (
    DEFAULT_GEMINI_EMBEDDING_DIMENSION,
    GeminiEmbeddingModel,
)


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


@pytest.mark.asyncio
async def test_gemini_embedding_single_text() -> None:
    """Test 1: Verify single text embedding generation."""
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
    """Test 2: Verify batch text embedding generation."""
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
    """Test 3: Verify embed_chunk creates an immutable EmbeddingRecord from a TextChunk."""
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


def test_gemini_embedding_missing_api_key_error() -> None:
    """Test 4: Verify ValueError when api_key is missing and no client is injected."""
    adapter = GeminiEmbeddingModel(api_key="")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        adapter._get_client()


def test_gemini_embedding_missing_dependency_error() -> None:
    """Test 5: Verify clear RuntimeError when google-genai is not installed."""
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
    """Test 6: Verify exponential retry when encountering 429 or 503 during embedding."""
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
async def test_gemini_embedding_input_validation() -> None:
    """Test 7: Verify strict input validation for empty texts and invalid inputs."""
    adapter = GeminiEmbeddingModel(
        api_key="fake-key", client=FakeEmbeddingGenAIClient()
    )

    with pytest.raises(EvidenceValidationError, match="empty or whitespace"):
        await adapter.embed_text("   ")

    with pytest.raises(TypeError, match="cannot be None"):
        await adapter.embed_text(None)  # type: ignore[arg-type]

    with pytest.raises(EvidenceValidationError, match="non-empty string"):
        await adapter.embed_batch(["valid", ""])

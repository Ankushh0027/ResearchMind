"""Google Gemini embedding adapter implementing EmbeddingModelProtocol."""

import asyncio
import logging
import random
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from pydantic import ValidationError

from app.common.errors import EvidenceValidationError, ResearchMindError
from app.rag.chunking import TextChunk
from app.rag.embeddings import (
    EmbeddingRecord,
    validate_dense_vector,
)
from app.rag.protocols import EmbeddingModelProtocol

logger = logging.getLogger("researchmind.rag.gemini")

R = TypeVar("R")
DEFAULT_GEMINI_EMBEDDING_DIMENSION = 768


def _is_retryable_error(exc: Exception) -> bool:
    """Determine whether an exception represents a transient, retryable failure."""
    status_code = getattr(exc, "status_code", getattr(exc, "code", None))
    if status_code in (429, 500, 502, 503, 504):
        return True

    err_str = str(exc).upper()
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


class GeminiEmbeddingModel(EmbeddingModelProtocol):
    """Production-grade Google Gemini dense embedding generator."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "text-embedding-004",
        dimension: int = DEFAULT_GEMINI_EMBEDDING_DIMENSION,
        max_retries: int = 3,
        initial_retry_delay_seconds: float = 1.0,
        max_retry_delay_seconds: float = 10.0,
        client: Any = None,
    ) -> None:
        self.api_key = api_key or ""
        self.model_name = model_name.strip()
        if not self.model_name:
            raise EvidenceValidationError(
                "model_name must not be empty or whitespace only"
            )
        if (
            not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension <= 0
        ):
            raise EvidenceValidationError(
                f"dimension must be a positive integer, got {dimension}",
                {"dimension": dimension},
            )
        self._dimension = dimension
        self.max_retries = max(0, max_retries)
        self.initial_retry_delay_seconds = max(0.01, initial_retry_delay_seconds)
        self.max_retry_delay_seconds = max(
            self.initial_retry_delay_seconds, max_retry_delay_seconds
        )
        self._client = client

    @property
    def dimension(self) -> int:
        """Return the dense vector dimensionality produced by this model."""
        return self._dimension

    def _get_client(self) -> Any:
        """Resolve or lazily initialize the Google GenAI SDK client."""
        if self._client is not None:
            return self._client

        if not self.api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY is required for GeminiEmbeddingModel when no client is injected."
            )

        try:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
            return self._client
        except ImportError as e:
            raise RuntimeError(
                "google-genai is required for GeminiEmbeddingModel. "
                "Install with: pip install google-genai"
            ) from e

    async def _execute_with_retry(
        self,
        operation_name: str,
        func: Callable[[], Coroutine[Any, Any, R]],
    ) -> R:
        """Execute an asynchronous embedding operation with exponential backoff and jitter."""
        attempt = 0
        while True:
            try:
                return await func()
            except asyncio.CancelledError:
                logger.info("Embedding operation '%s' was cancelled.", operation_name)
                raise
            except Exception as exc:
                if isinstance(
                    exc,
                    (ValidationError, EvidenceValidationError, TypeError, ValueError),
                ) and not isinstance(exc, ResearchMindError):
                    raise

                if not _is_retryable_error(exc) or attempt >= self.max_retries:
                    logger.error(
                        "Embedding operation '%s' failed (attempt %d/%d, retryable=%s): %s",
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
                    "Embedding operation '%s' encountered transient error (attempt %d/%d): %s. Retrying in %.2fs...",
                    operation_name,
                    attempt + 1,
                    self.max_retries,
                    type(exc).__name__,
                    delay,
                )

                await asyncio.sleep(delay)
                attempt += 1

    async def embed_text(self, text: str) -> tuple[float, ...]:
        """Generate a dense embedding vector for a single text string."""
        if text is None:
            raise TypeError("Text to embed cannot be None")
        if not isinstance(text, str):
            raise TypeError(f"Expected str for text, got {type(text).__name__}")
        if not text.strip():
            raise EvidenceValidationError(
                "Text to embed must not be empty or whitespace only"
            )

        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate dense embedding vectors for a batch of text strings."""
        if texts is None or not isinstance(texts, list):
            raise TypeError("texts must be a list of strings")
        if not texts:
            return []

        for idx, t in enumerate(texts):
            if t is None or not isinstance(t, str) or not t.strip():
                raise EvidenceValidationError(
                    f"Text at index {idx} must be a non-empty string"
                )

        client = self._get_client()
        model = self.model_name

        async def _call() -> Any:
            # Check modern Google GenAI Client .aio.models.embed_content
            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                return await client.aio.models.embed_content(
                    model=model,
                    contents=texts,
                )

            # Fallback for injected or mock client interfaces
            if hasattr(client, "embed_content"):
                func = client.embed_content
                if asyncio.iscoroutinefunction(func):
                    return await func(model=model, contents=texts)
                return await asyncio.to_thread(func, model=model, contents=texts)

            if hasattr(client, "embed_batch"):
                func = client.embed_batch
                if asyncio.iscoroutinefunction(func):
                    return await func(texts)
                return await asyncio.to_thread(func, texts)

            raise RuntimeError(
                f"Injected client {type(client).__name__} does not support embedding generation."
            )

        response = await self._execute_with_retry("embed_batch", _call)

        # Parse SDK response or mock list
        results: list[tuple[float, ...]] = []

        if isinstance(response, list):
            for item in response:
                if isinstance(item, (tuple, list)):
                    vec = validate_dense_vector(
                        item, expected_dimension=self._dimension
                    )
                    results.append(vec)
                elif hasattr(item, "values"):
                    vec = validate_dense_vector(
                        item.values, expected_dimension=self._dimension
                    )
                    results.append(vec)
            return results

        embeddings = getattr(response, "embeddings", None)
        if embeddings is not None:
            for emb in embeddings:
                values = getattr(emb, "values", emb)
                vec = validate_dense_vector(values, expected_dimension=self._dimension)
                results.append(vec)
            return results

        # If single embedding returned
        embedding = getattr(response, "embedding", None)
        if embedding is not None:
            values = getattr(embedding, "values", embedding)
            vec = validate_dense_vector(values, expected_dimension=self._dimension)
            return [vec]

        raise ValueError(
            f"Unexpected response format from embedding provider: {response!r}"
        )

    async def embed_chunk(self, chunk: TextChunk) -> EmbeddingRecord:
        """Generate an EmbeddingRecord for an upstream TextChunk."""
        if chunk is None or not isinstance(chunk, TextChunk):
            raise TypeError(f"Expected TextChunk, got {type(chunk).__name__}")
        vec = await self.embed_text(chunk.text)
        return EmbeddingRecord.from_chunk(
            chunk=chunk,
            vector=vec,
            model_name=self.model_name,
        )


__all__ = [
    "DEFAULT_GEMINI_EMBEDDING_DIMENSION",
    "GeminiEmbeddingModel",
]

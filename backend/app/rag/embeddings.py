"""Provider-neutral embedding domain models, validation, and deterministic reference implementation.

Provides immutable EmbeddingRecord schemas, strict vector validation (finite numeric, dimension match,
no NaN/Inf), and an offline deterministic MockEmbeddingModel adhering to EmbeddingModelProtocol.
"""

import hashlib
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.errors import EvidenceValidationError
from app.rag.chunking import TextChunk
from app.rag.protocols import EmbeddingModelProtocol

DEFAULT_EMBEDDING_DIMENSION = 64


def _utc_now() -> datetime:
    return datetime.now(UTC)


def generate_embedding_id(prefix: str = "emb") -> str:
    """Generate a unique embedding record identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def validate_dense_vector(
    vector: tuple[float, ...] | list[float],
    expected_dimension: int | None = None,
) -> tuple[float, ...]:
    """Validate that a vector is non-empty, contains only finite numeric values, and matches expected dimension."""
    if vector is None:
        raise TypeError("Vector cannot be None")
    if not isinstance(vector, (tuple, list)):
        raise TypeError(
            f"Vector must be a tuple or list of floats, got {type(vector).__name__}"
        )
    if len(vector) == 0:
        raise EvidenceValidationError("Vector must not be empty", {"vector_length": 0})

    validated: list[float] = []
    for idx, val in enumerate(vector):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise EvidenceValidationError(
                f"Vector component at index {idx} must be numeric, got {type(val).__name__}",
                {"index": idx, "value": val},
            )
        f_val = float(val)
        if math.isnan(f_val):
            raise EvidenceValidationError(
                f"Vector component at index {idx} is NaN",
                {"index": idx, "value": "NaN"},
            )
        if math.isinf(f_val):
            raise EvidenceValidationError(
                f"Vector component at index {idx} is infinite",
                {"index": idx, "value": str(f_val)},
            )
        validated.append(f_val)

    vec_tuple = tuple(validated)
    if expected_dimension is not None:
        if expected_dimension <= 0:
            raise EvidenceValidationError(
                f"Expected dimension must be positive, got {expected_dimension}",
                {"dimension": expected_dimension},
            )
        if len(vec_tuple) != expected_dimension:
            raise EvidenceValidationError(
                f"Vector dimension mismatch: expected {expected_dimension}, got {len(vec_tuple)}",
                {
                    "expected_dimension": expected_dimension,
                    "actual_dimension": len(vec_tuple),
                },
            )
    return vec_tuple


class EmbeddingRecord(BaseModel):
    """Immutable vector embedding record associated with a parent TextChunk and EvidenceRecord."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding_id: str = Field(
        default_factory=generate_embedding_id,
        min_length=1,
        description="Unique embedding record identifier",
    )
    chunk_id: str = Field(
        ...,
        min_length=1,
        description="Referenced TextChunk identifier",
    )
    evidence_id: str = Field(
        ...,
        min_length=1,
        description="Parent EvidenceRecord identifier",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="Associated research run identifier for multi-tenant isolation",
    )
    vector: tuple[float, ...] = Field(
        ...,
        min_length=1,
        description="Dense float embedding vector",
    )
    dimension: int = Field(
        ...,
        ge=1,
        description="Dimensionality of the dense vector",
    )
    model_name: str = Field(
        default="mock-embedding-v1",
        min_length=1,
        description="Provider-neutral embedding model identifier",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Passive metadata payload",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Timestamp when the embedding was generated",
    )

    @property
    def dimensions(self) -> int:
        """Alias for dimension."""
        return self.dimension

    @field_validator("embedding_id", "chunk_id", "evidence_id", "run_id", "model_name")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("String fields must not be empty or whitespace only")
        return v.strip()

    @field_validator("vector", mode="before")
    @classmethod
    def validate_vector_components(cls, v: Any) -> tuple[float, ...]:
        return validate_dense_vector(v)

    @model_validator(mode="after")
    def validate_dimension_and_identity(self) -> "EmbeddingRecord":
        if len(self.vector) != self.dimension:
            raise ValueError(
                f"Vector length ({len(self.vector)}) does not match declared dimension ({self.dimension})"
            )
        if self.embedding_id == self.chunk_id:
            raise ValueError(
                f"embedding_id '{self.embedding_id}' must not equal chunk_id"
            )
        if self.embedding_id == self.evidence_id:
            raise ValueError(
                f"embedding_id '{self.embedding_id}' must not equal evidence_id"
            )
        return self

    @classmethod
    def from_chunk(
        cls,
        chunk: TextChunk,
        vector: tuple[float, ...] | list[float],
        model_name: str = "mock-embedding-v1",
        embedding_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "EmbeddingRecord":
        """Factory creating an EmbeddingRecord from an upstream TextChunk without mutating the chunk."""
        if chunk is None or not isinstance(chunk, TextChunk):
            raise TypeError(f"Expected TextChunk, got {type(chunk).__name__}")
        validated_vec = validate_dense_vector(vector)
        chunk_meta = dict(chunk.metadata) if chunk.metadata else {}
        if metadata:
            chunk_meta.update(metadata)
        # Ensure provenance is strictly maintained
        chunk_meta["chunk_id"] = chunk.chunk_id
        chunk_meta["evidence_id"] = chunk.evidence_id
        chunk_meta["run_id"] = chunk.run_id

        return cls(
            embedding_id=embedding_id or generate_embedding_id(),
            chunk_id=chunk.chunk_id,
            evidence_id=chunk.evidence_id,
            run_id=chunk.run_id,
            vector=validated_vec,
            dimension=len(validated_vec),
            model_name=model_name,
            metadata=chunk_meta,
        )


class MockEmbeddingModel(EmbeddingModelProtocol):
    """Deterministic, provider-neutral, offline embedding generator for testing and local execution."""

    def __init__(
        self,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        model_name: str = "mock-embedding-v1",
    ) -> None:
        if (
            not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension <= 0
        ):
            raise EvidenceValidationError(
                f"dimension must be a positive integer, got {dimension}",
                {"dimension": dimension},
            )
        if not model_name or not model_name.strip():
            raise EvidenceValidationError(
                "model_name must not be empty or whitespace only"
            )
        self._dimension = dimension
        self.model_name = model_name.strip()

    @property
    def dimension(self) -> int:
        return self._dimension

    def _generate_vector(self, text: str) -> tuple[float, ...]:
        if text is None:
            raise TypeError("Text to embed cannot be None")
        if not isinstance(text, str):
            raise TypeError(f"Expected str for text, got {type(text).__name__}")
        if not text.strip():
            raise EvidenceValidationError(
                "Text to embed must not be empty or whitespace only"
            )

        raw_components = [0.0] * self._dimension
        for i in range(self._dimension):
            seed = f"{text}_{i}".encode()
            h_val = int(hashlib.sha256(seed).hexdigest()[:8], 16)
            # Map to range [-1.0, 1.0]
            val = (h_val / 0xFFFFFFFF) * 2.0 - 1.0
            raw_components[i] = val

        # Normalize to unit sphere (L2 norm = 1.0)
        norm = math.sqrt(sum(x * x for x in raw_components))
        if norm == 0.0:
            norm = 1.0
        normalized = tuple(round(x / norm, 8) for x in raw_components)
        return normalized

    async def embed_text(self, text: str) -> tuple[float, ...]:
        """Generate a dense embedding vector for a single text string."""
        return self._generate_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate dense embeddings for a batch of text strings."""
        if texts is None or not isinstance(texts, list):
            raise TypeError("texts must be a list of strings")
        return [self._generate_vector(t) for t in texts]

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
    "DEFAULT_EMBEDDING_DIMENSION",
    "EmbeddingModelProtocol",
    "EmbeddingRecord",
    "MockEmbeddingModel",
    "generate_embedding_id",
    "validate_dense_vector",
]

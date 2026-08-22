"""Provider-neutral vector memory and embedding model protocols."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class VectorPoint(BaseModel):
    """Normalized embedding vector and metadata payload for vector storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    point_id: str = Field(
        ..., min_length=1, description="Unique vector point identifier"
    )
    vector: tuple[float, ...] = Field(
        ..., min_length=1, description="Dense embedding vector"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Metadata associated with this vector"
    )


class VectorSearchResult(BaseModel):
    """Result item returned from vector similarity searches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    point_id: str = Field(..., min_length=1, description="Matched point identifier")
    score: float = Field(
        ..., ge=-1.0, le=1.0, description="Cosine or dot-product similarity score"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Stored payload metadata"
    )


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Protocol for vector indexing and similarity retrieval."""

    async def upsert_vectors(
        self, collection_name: str, points: list[VectorPoint]
    ) -> int:
        """Upsert dense vector points into a named collection, returning the count of upserted items."""
        ...

    async def search_vectors(
        self,
        collection_name: str,
        query_vector: tuple[float, ...] | list[float],
        limit: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Perform nearest-neighbor similarity search against a collection."""
        ...

    async def delete_collection(self, collection_name: str) -> None:
        """Delete a named vector collection."""
        ...


@runtime_checkable
class EmbeddingModelProtocol(Protocol):
    """Protocol for dense vector embedding generation."""

    @property
    def dimension(self) -> int:
        """Return the vector dimensionality produced by this model."""
        ...

    async def embed_text(self, text: str) -> tuple[float, ...]:
        """Generate a dense embedding vector for a single text string."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Generate dense embeddings for a batch of text strings."""
        ...

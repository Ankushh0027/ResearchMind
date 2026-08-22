"""Unit tests for RAG protocols, VectorPoint, and VectorSearchResult schemas."""

import pytest
from pydantic import ValidationError

from app.rag.protocols import (
    EmbeddingModelProtocol,
    VectorPoint,
    VectorSearchResult,
    VectorStoreProtocol,
)


class DummyVectorStore(VectorStoreProtocol):
    """Minimal compliant implementation of VectorStoreProtocol for testing."""

    async def upsert_vectors(
        self, _collection_name: str, points: list[VectorPoint]
    ) -> int:
        return len(points)

    async def search_vectors(
        self,
        _collection_name: str,
        _query_vector: tuple[float, ...] | list[float],
        _limit: int = 10,
        _filter_metadata: dict[str, object] | None = None,
    ) -> list[VectorSearchResult]:
        return [
            VectorSearchResult(point_id="p1", score=0.92, payload={"text": "match"})
        ]

    async def delete_collection(self, _collection_name: str) -> None:
        pass


class DummyEmbeddingModel(EmbeddingModelProtocol):
    """Minimal compliant implementation of EmbeddingModelProtocol for testing."""

    @property
    def dimension(self) -> int:
        return 4

    async def embed_text(self, _text: str) -> tuple[float, ...]:
        return (0.1, 0.2, 0.3, 0.4)

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [(0.1, 0.2, 0.3, 0.4) for _ in texts]


def test_vector_point_validation_and_immutability() -> None:
    """Verify VectorPoint data constraints and frozen configuration."""
    pt = VectorPoint(
        point_id="pt_001",
        vector=(0.05, 0.12, 0.99),
        payload={"doc_id": "doc_123", "subtask_id": "t1"},
    )
    assert pt.point_id == "pt_001"
    assert len(pt.vector) == 3

    with pytest.raises(ValidationError):
        pt.point_id = "pt_mutated"

    # Vector cannot be empty
    with pytest.raises(ValidationError):
        VectorPoint(point_id="empty_vec", vector=(), payload={})


def test_vector_store_protocol_compliance() -> None:
    """Verify isinstance checks on VectorStoreProtocol."""
    store = DummyVectorStore()
    assert isinstance(store, VectorStoreProtocol)


def test_embedding_model_protocol_compliance() -> None:
    """Verify isinstance checks on EmbeddingModelProtocol."""
    model = DummyEmbeddingModel()
    assert isinstance(model, EmbeddingModelProtocol)
    assert model.dimension == 4

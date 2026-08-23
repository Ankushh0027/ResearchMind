"""In-memory vector store implementing VectorStoreProtocol with cosine similarity.

Provides hermetic, provider-neutral, in-memory dense vector indexing and nearest-neighbor
similarity search with exact-match metadata filtering and deterministic tie-breaking.
"""

import math
from typing import Any

from app.common.errors import (
    EvidenceValidationError,
    VectorDimensionMismatchError,
)
from app.rag.embeddings import validate_dense_vector
from app.rag.protocols import (
    VectorPoint,
    VectorSearchResult,
    VectorStoreProtocol,
)

DEFAULT_STORE_DIMENSION = 64


def compute_cosine_similarity(
    vec_a: tuple[float, ...], vec_b: tuple[float, ...]
) -> float:
    """Compute cosine similarity between two dense float vectors with clamped output [-1.0, 1.0]."""
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"Vectors must have identical dimensions: {len(vec_a)} != {len(vec_b)}"
        )

    dot_product = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0

    for a, b in zip(vec_a, vec_b, strict=True):
        dot_product += a * b
        norm_a_sq += a * a
        norm_b_sq += b * b

    if norm_a_sq == 0.0 or norm_b_sq == 0.0:
        return 0.0

    norm_a = math.sqrt(norm_a_sq)
    norm_b = math.sqrt(norm_b_sq)
    raw_sim = dot_product / (norm_a * norm_b)

    # Clamp to [-1.0, 1.0] to guard against floating-point epsilon overshoots
    return max(-1.0, min(1.0, raw_sim))


class InMemoryVectorStore(VectorStoreProtocol):
    """In-memory reference implementation of VectorStoreProtocol."""

    def __init__(self, dimension: int = DEFAULT_STORE_DIMENSION) -> None:
        if (
            not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension <= 0
        ):
            raise EvidenceValidationError(
                f"dimension must be a positive integer, got {dimension}",
                {"dimension": dimension},
            )
        self.dimension = dimension
        self._collections: dict[str, dict[str, VectorPoint]] = {}

    def _ensure_collection(self, collection_name: str) -> dict[str, VectorPoint]:
        if not collection_name or not collection_name.strip():
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )
        clean_name = collection_name.strip()
        if clean_name not in self._collections:
            self._collections[clean_name] = {}
        return self._collections[clean_name]

    async def upsert_vectors(
        self, collection_name: str, points: list[VectorPoint]
    ) -> int:
        """Upsert dense vector points into a named collection, returning count of upserted items."""
        if points is None or not isinstance(points, list):
            raise TypeError("points must be a list of VectorPoint instances")

        collection = self._ensure_collection(collection_name)

        for pt in points:
            if not isinstance(pt, VectorPoint):
                raise TypeError(f"Expected VectorPoint, got {type(pt).__name__}")
            if len(pt.vector) != self.dimension:
                raise VectorDimensionMismatchError(
                    expected_dimension=self.dimension,
                    actual_dimension=len(pt.vector),
                    entity_id=pt.point_id,
                )
            # Validate numeric and finiteness invariants
            validate_dense_vector(pt.vector, expected_dimension=self.dimension)
            collection[pt.point_id] = pt

        return len(points)

    async def search_vectors(
        self,
        collection_name: str,
        query_vector: tuple[float, ...] | list[float],
        limit: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Perform nearest-neighbor cosine similarity search against a named collection."""
        if not collection_name or not collection_name.strip():
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )
        clean_name = collection_name.strip()

        if limit <= 0:
            raise EvidenceValidationError(
                f"limit must be a positive integer, got {limit}",
                {"limit": limit},
            )

        validated_query = validate_dense_vector(
            query_vector, expected_dimension=self.dimension
        )

        collection = self._collections.get(clean_name, {})
        if not collection:
            return []

        scored_results: list[VectorSearchResult] = []

        for point in collection.values():
            # Check metadata filter match if provided
            if filter_metadata:
                match = True
                for k, v in filter_metadata.items():
                    if point.payload.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            score = compute_cosine_similarity(validated_query, point.vector)
            scored_results.append(
                VectorSearchResult(
                    point_id=point.point_id,
                    score=score,
                    payload=point.payload,
                )
            )

        # Sort by (-score, point_id) for deterministic tie-breaking
        scored_results.sort(key=lambda res: (-round(res.score, 6), res.point_id))

        return scored_results[:limit]

    async def delete_collection(self, collection_name: str) -> None:
        """Delete a named vector collection from memory."""
        if not collection_name or not collection_name.strip():
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )
        clean_name = collection_name.strip()
        self._collections.pop(clean_name, None)

    def get_point(self, collection_name: str, point_id: str) -> VectorPoint | None:
        """Retrieve a stored VectorPoint by identifier."""
        clean_name = collection_name.strip()
        return self._collections.get(clean_name, {}).get(point_id)

    def count(self, collection_name: str) -> int:
        """Return the number of vector points stored in a collection."""
        clean_name = collection_name.strip()
        return len(self._collections.get(clean_name, {}))

    def has_collection(self, collection_name: str) -> bool:
        """Check whether a collection exists."""
        clean_name = collection_name.strip()
        return clean_name in self._collections


__all__ = [
    "DEFAULT_STORE_DIMENSION",
    "InMemoryVectorStore",
    "compute_cosine_similarity",
]

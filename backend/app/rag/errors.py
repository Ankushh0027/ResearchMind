"""RAG domain exception re-exports for the rag package."""

from app.common.errors import (
    CollectionNotFoundError,
    EmptyVectorQueryError,
    EvidenceValidationError,
    RAGError,
    VectorDimensionMismatchError,
)

__all__ = [
    "CollectionNotFoundError",
    "EmptyVectorQueryError",
    "EvidenceValidationError",
    "RAGError",
    "VectorDimensionMismatchError",
]

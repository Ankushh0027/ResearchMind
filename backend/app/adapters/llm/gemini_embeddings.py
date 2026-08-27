"""Google Gemini embedding adapter module re-exported under app.adapters.llm."""

from app.rag.gemini import (
    DEFAULT_GEMINI_EMBEDDING_DIMENSION,
    GeminiEmbeddingModel,
)

__all__ = [
    "DEFAULT_GEMINI_EMBEDDING_DIMENSION",
    "GeminiEmbeddingModel",
]

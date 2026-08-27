"""Factory constructors for embedding model and vector store adapters."""

from typing import Any

from app.config.settings import AppSettings, get_settings
from app.rag.embeddings import MockEmbeddingModel
from app.rag.gemini import GeminiEmbeddingModel
from app.rag.protocols import EmbeddingModelProtocol, VectorStoreProtocol
from app.rag.qdrant import QdrantVectorStore
from app.rag.store import InMemoryVectorStore


def create_embedding_model(
    settings: AppSettings | None = None,
    client: Any = None,
) -> EmbeddingModelProtocol:
    """Instantiate configured EmbeddingModelProtocol (MockEmbeddingModel or GeminiEmbeddingModel)."""
    cfg = settings or get_settings()
    provider = cfg.embedding_provider.lower()

    if provider == "gemini":
        return GeminiEmbeddingModel(
            api_key=cfg.gemini_api_key,
            model_name=cfg.gemini_embedding_model,
            request_timeout_seconds=cfg.gemini_request_timeout_seconds,
            max_retries=cfg.gemini_max_retries,
            initial_retry_delay_seconds=cfg.gemini_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.gemini_max_retry_delay_seconds,
            client=client,
        )

    if provider in ("in_memory", "mock"):
        if client is not None and isinstance(client, EmbeddingModelProtocol):
            return client
        return MockEmbeddingModel()

    raise ValueError(
        f"Unsupported EMBEDDING_PROVIDER: '{cfg.embedding_provider}'. Supported values: 'in_memory', 'mock', 'gemini'."
    )


def create_vector_store(
    settings: AppSettings | None = None,
    client: Any = None,
) -> VectorStoreProtocol:
    """Instantiate configured VectorStoreProtocol (InMemoryVectorStore or QdrantVectorStore)."""
    cfg = settings or get_settings()
    provider = cfg.vector_store_provider.lower()

    if provider == "qdrant":
        return QdrantVectorStore(
            url=cfg.qdrant_url,
            api_key=cfg.qdrant_api_key,
            dimension=cfg.qdrant_vector_size,
            distance=cfg.qdrant_distance,
            request_timeout_seconds=cfg.qdrant_request_timeout_seconds,
            max_retries=cfg.qdrant_max_retries,
            initial_retry_delay_seconds=cfg.qdrant_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.qdrant_max_retry_delay_seconds,
            client=client,
        )

    if provider in ("in_memory", "mock"):
        if client is not None and isinstance(client, VectorStoreProtocol):
            return client
        return InMemoryVectorStore(dimension=cfg.qdrant_vector_size)

    raise ValueError(
        f"Unsupported VECTOR_STORE_PROVIDER: '{cfg.vector_store_provider}'. Supported values: 'in_memory', 'mock', 'qdrant'."
    )


__all__ = [
    "create_embedding_model",
    "create_vector_store",
]

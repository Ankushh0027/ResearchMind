"""Factory constructors for embedding model adapters."""

from typing import Any

from app.config.settings import AppSettings, get_settings
from app.rag.embeddings import MockEmbeddingModel
from app.rag.gemini import GeminiEmbeddingModel
from app.rag.protocols import EmbeddingModelProtocol


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


__all__ = ["create_embedding_model"]

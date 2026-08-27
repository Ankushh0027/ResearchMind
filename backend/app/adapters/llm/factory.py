"""Factory constructors for LLM client adapters."""

from typing import Any

from app.adapters.llm.base import LLMClientProtocol
from app.adapters.llm.gemini import GeminiLLMClient
from app.adapters.llm.mock_llm import MockLLMClient
from app.config.settings import AppSettings, get_settings


def create_llm_client(
    settings: AppSettings | None = None,
    client: Any = None,
) -> LLMClientProtocol:
    """Instantiate configured LLMClientProtocol (MockLLMClient or GeminiLLMClient)."""
    cfg = settings or get_settings()
    provider = cfg.llm_provider.lower()

    if provider == "gemini":
        return GeminiLLMClient(
            api_key=cfg.gemini_api_key,
            model_name=cfg.gemini_model,
            fast_model_name=cfg.gemini_fast_model,
            temperature=cfg.gemini_temperature,
            max_output_tokens=cfg.gemini_max_output_tokens,
            request_timeout_seconds=cfg.gemini_request_timeout_seconds,
            max_retries=cfg.gemini_max_retries,
            initial_retry_delay_seconds=cfg.gemini_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.gemini_max_retry_delay_seconds,
            client=client,
        )

    if provider in ("in_memory", "mock"):
        if client is not None and isinstance(client, LLMClientProtocol):
            return client
        return MockLLMClient()

    raise ValueError(
        f"Unsupported LLM_PROVIDER: '{cfg.llm_provider}'. Supported values: 'in_memory', 'mock', 'gemini'."
    )


__all__ = ["create_llm_client"]

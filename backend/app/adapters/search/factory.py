"""Factory constructors for web and academic search client adapters."""

from typing import Any

from app.adapters.search.arxiv import ArxivSearchAdapter
from app.adapters.search.base import SearchClientProtocol
from app.adapters.search.mock_search import MockSearchClient
from app.adapters.search.tavily import TavilySearchAdapter
from app.config.settings import AppSettings, get_settings


def create_search_client(
    settings: AppSettings | None = None,
    client: Any = None,
) -> SearchClientProtocol:
    """Instantiate configured SearchClientProtocol for general web search."""
    cfg = settings or get_settings()
    provider = cfg.search_provider.lower()

    if provider == "tavily":
        return TavilySearchAdapter(
            api_key=cfg.tavily_api_key,
            api_url=cfg.tavily_api_url,
            request_timeout_seconds=cfg.tavily_request_timeout_seconds,
            max_retries=cfg.tavily_max_retries,
            initial_retry_delay_seconds=cfg.tavily_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.tavily_max_retry_delay_seconds,
            client=client,
        )

    if provider == "arxiv":
        return ArxivSearchAdapter(
            api_url=cfg.arxiv_api_url,
            request_timeout_seconds=cfg.arxiv_request_timeout_seconds,
            max_retries=cfg.arxiv_max_retries,
            initial_retry_delay_seconds=cfg.arxiv_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.arxiv_max_retry_delay_seconds,
            client=client,
        )

    if provider in ("in_memory", "mock"):
        if client is not None and isinstance(client, SearchClientProtocol):
            return client
        return MockSearchClient()

    raise ValueError(
        f"Unsupported SEARCH_PROVIDER: '{cfg.search_provider}'. Supported values: 'in_memory', 'mock', 'tavily', 'arxiv'."
    )


def create_academic_search_client(
    settings: AppSettings | None = None,
    client: Any = None,
) -> SearchClientProtocol:
    """Instantiate configured SearchClientProtocol for academic search."""
    cfg = settings or get_settings()
    provider = cfg.academic_search_provider.lower()

    if provider == "arxiv":
        return ArxivSearchAdapter(
            api_url=cfg.arxiv_api_url,
            request_timeout_seconds=cfg.arxiv_request_timeout_seconds,
            max_retries=cfg.arxiv_max_retries,
            initial_retry_delay_seconds=cfg.arxiv_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.arxiv_max_retry_delay_seconds,
            client=client,
        )

    if provider == "tavily":
        return TavilySearchAdapter(
            api_key=cfg.tavily_api_key,
            api_url=cfg.tavily_api_url,
            request_timeout_seconds=cfg.tavily_request_timeout_seconds,
            max_retries=cfg.tavily_max_retries,
            initial_retry_delay_seconds=cfg.tavily_initial_retry_delay_seconds,
            max_retry_delay_seconds=cfg.tavily_max_retry_delay_seconds,
            client=client,
        )

    if provider in ("in_memory", "mock"):
        if client is not None and isinstance(client, SearchClientProtocol):
            return client
        return MockSearchClient()

    raise ValueError(
        f"Unsupported ACADEMIC_SEARCH_PROVIDER: '{cfg.academic_search_provider}'. Supported values: 'in_memory', 'mock', 'arxiv', 'tavily'."
    )


__all__ = [
    "create_academic_search_client",
    "create_search_client",
]

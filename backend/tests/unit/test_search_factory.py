"""Unit tests for search adapter factories."""

from unittest.mock import MagicMock

import pytest

from app.adapters.search.arxiv import ArxivSearchAdapter
from app.adapters.search.base import SearchClientProtocol
from app.adapters.search.factory import (
    create_academic_search_client,
    create_search_client,
)
from app.adapters.search.mock_search import MockSearchClient
from app.adapters.search.tavily import TavilySearchAdapter
from app.config.settings import AppSettings


class TestSearchFactory:
    """Test suite for create_search_client and create_academic_search_client."""

    def test_search_factory_in_memory_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default SEARCH_PROVIDER in_memory should instantiate MockSearchClient."""
        monkeypatch.setenv("SEARCH_PROVIDER", "in_memory")
        settings = AppSettings()
        client = create_search_client(settings=settings)
        assert isinstance(client, MockSearchClient)

    def test_search_factory_tavily(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SEARCH_PROVIDER tavily should instantiate TavilySearchAdapter."""
        monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        settings = AppSettings()
        client = create_search_client(settings=settings)
        assert isinstance(client, TavilySearchAdapter)
        assert client.api_key == "tvly-test-key"

    def test_search_factory_arxiv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SEARCH_PROVIDER arxiv should instantiate ArxivSearchAdapter."""
        monkeypatch.setenv("SEARCH_PROVIDER", "arxiv")
        settings = AppSettings()
        client = create_search_client(settings=settings)
        assert isinstance(client, ArxivSearchAdapter)

    def test_academic_search_factory_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default ACADEMIC_SEARCH_PROVIDER in_memory should instantiate MockSearchClient."""
        monkeypatch.setenv("ACADEMIC_SEARCH_PROVIDER", "in_memory")
        settings = AppSettings()
        client = create_academic_search_client(settings=settings)
        assert isinstance(client, MockSearchClient)

    def test_academic_search_factory_arxiv(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ACADEMIC_SEARCH_PROVIDER arxiv should instantiate ArxivSearchAdapter."""
        monkeypatch.setenv("ACADEMIC_SEARCH_PROVIDER", "arxiv")
        settings = AppSettings()
        client = create_academic_search_client(settings=settings)
        assert isinstance(client, ArxivSearchAdapter)

    def test_academic_search_factory_tavily(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ACADEMIC_SEARCH_PROVIDER tavily should instantiate TavilySearchAdapter."""
        monkeypatch.setenv("ACADEMIC_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-academic-key")
        settings = AppSettings()
        client = create_academic_search_client(settings=settings)
        assert isinstance(client, TavilySearchAdapter)
        assert client.api_key == "tvly-academic-key"

    def test_factory_injected_instance(self) -> None:
        """Injected test double should be returned directly."""
        mock_client = MagicMock(spec=SearchClientProtocol)
        settings = AppSettings()
        res = create_search_client(settings=settings, client=mock_client)
        assert res is mock_client

    def test_factory_unsupported_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unsupported provider setting should raise ValidationError."""
        from pydantic import ValidationError

        monkeypatch.setenv("SEARCH_PROVIDER", "bing_unsupported")
        with pytest.raises(ValidationError):
            AppSettings()

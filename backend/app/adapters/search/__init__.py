"""Search adapter interfaces, query contracts, providers, and factories."""

from app.adapters.search.arxiv import ArxivSearchAdapter
from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)
from app.adapters.search.factory import (
    create_academic_search_client,
    create_search_client,
)
from app.adapters.search.mock_search import MockSearchClient
from app.adapters.search.tavily import TavilySearchAdapter

__all__ = [
    "ArxivSearchAdapter",
    "MockSearchClient",
    "SearchClientProtocol",
    "SearchHit",
    "SearchQuery",
    "TavilySearchAdapter",
    "create_academic_search_client",
    "create_search_client",
]

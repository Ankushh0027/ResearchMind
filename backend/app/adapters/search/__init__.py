"""Search adapter interfaces, query contracts, and mock providers."""

from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)
from app.adapters.search.mock_search import MockSearchClient

__all__ = [
    "MockSearchClient",
    "SearchClientProtocol",
    "SearchHit",
    "SearchQuery",
]

"""Deterministic mock search client for testing research workflows."""

from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)


class MockSearchClient(SearchClientProtocol):
    """Deterministic mock search client returning configured search hits without network I/O."""

    def __init__(
        self,
        default_hits: list[SearchHit] | None = None,
        query_map: dict[str, list[SearchHit]] | None = None,
    ) -> None:
        self.default_hits = default_hits or [
            SearchHit(
                url="https://example.org/sample-paper",
                title="Sample Research Paper",
                snippet="Empirical findings show robust convergence across benchmark suites.",
                score=0.95,
                domain="example.org",
                authors=("A. Scientist", "B. Researcher"),
                publication_date="2026-01-15",
            )
        ]
        self.query_map = query_map or {}
        self.recorded_queries: list[SearchQuery] = []

    def set_query_results(self, query_substring: str, hits: list[SearchHit]) -> None:
        """Register specific search hits when a query matches the specified substring."""
        self.query_map[query_substring.lower()] = hits

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute mock search and return matched or default hits bounded by query.max_results."""
        self.recorded_queries.append(query)
        q_lower = query.query.lower()

        matched_hits: list[SearchHit] = self.default_hits
        for key, hits in self.query_map.items():
            if key in q_lower:
                matched_hits = hits
                break

        return matched_hits[: query.max_results]

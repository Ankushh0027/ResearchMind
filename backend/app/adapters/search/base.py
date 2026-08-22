"""Provider-neutral search query, search hit contracts, and client protocol."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    """Normalized search query dispatched to web or academic search providers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(..., min_length=1, description="Raw query string")
    max_results: int = Field(
        default=5, ge=1, le=50, description="Maximum number of hits to return"
    )
    filters: dict[str, Any] = Field(
        default_factory=dict, description="Domain, date range, or site filters"
    )


class SearchHit(BaseModel):
    """Atomic search result returned from a search query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(
        ...,
        min_length=1,
        description="Direct URL of the discovered web or academic source",
    )
    title: str = Field(..., min_length=1, description="Document title or page heading")
    snippet: str = Field(default="", description="Relevant contextual text snippet")
    score: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Provider relevance or rank score"
    )
    domain: str = Field(default="", description="Extracted root domain name")
    authors: tuple[str, ...] = Field(
        default_factory=tuple, description="Authors or publisher name"
    )
    publication_date: str | None = Field(
        default=None, description="ISO publication date if available"
    )


@runtime_checkable
class SearchClientProtocol(Protocol):
    """Protocol for web and academic search retrieval."""

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute search query and return normalized search hits."""
        ...

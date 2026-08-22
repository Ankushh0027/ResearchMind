"""External adapter layer: LLM inference, search providers, and storage bridges."""

from app.adapters.llm import LLMRequest, LLMResponse, MockLLMClient, ToolCall
from app.adapters.search import MockSearchClient, SearchHit, SearchQuery

__all__ = [
    "LLMRequest",
    "LLMResponse",
    "MockLLMClient",
    "MockSearchClient",
    "SearchHit",
    "SearchQuery",
    "ToolCall",
]

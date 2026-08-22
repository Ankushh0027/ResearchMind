"""Unit tests for MockLLMClient and MockSearchClient deterministic execution."""

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.llm.base import LLMRequest
from app.adapters.llm.mock_llm import MockLLMClient
from app.adapters.search.base import SearchHit, SearchQuery
from app.adapters.search.mock_search import MockSearchClient
from app.intelligence.protocols import LLMClientProtocol, SearchClientProtocol


class SampleStructuredOutput(BaseModel):
    """Test schema for structured LLM generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


@pytest.mark.asyncio
async def test_mock_llm_client_text_generation() -> None:
    """Verify MockLLMClient generates deterministic text and tracks requests."""
    client = MockLLMClient(default_response_text="Verified factual summary.")
    assert isinstance(client, LLMClientProtocol)

    req = LLMRequest(user_prompt="Analyze this evidence.")
    resp = await client.generate_text(req)

    assert resp.content == "Verified factual summary."
    assert resp.total_tokens == 75
    assert len(client.recorded_requests) == 1
    assert client.recorded_requests[0].user_prompt == "Analyze this evidence."


@pytest.mark.asyncio
async def test_mock_llm_client_structured_generation() -> None:
    """Verify MockLLMClient returns registered structured schema instance."""
    client = MockLLMClient()
    expected_output = SampleStructuredOutput(
        summary="Key finding insight", confidence=0.95
    )
    client.set_structured_response(SampleStructuredOutput, expected_output)

    result = await client.generate_structured(
        system_prompt="System instructions",
        user_prompt="Extract structured insight",
        response_schema=SampleStructuredOutput,
    )

    assert result == expected_output
    assert len(client.recorded_structured_prompts) == 1
    assert client.recorded_structured_prompts[0][1] == "Extract structured insight"


@pytest.mark.asyncio
async def test_mock_search_client_deterministic_query_matching() -> None:
    """Verify MockSearchClient matches query substrings and limits hit count."""
    client = MockSearchClient()
    assert isinstance(client, SearchClientProtocol)

    special_hit = SearchHit(
        url="https://arxiv.org/abs/2026.0001",
        title="Specific AI Safety Paper",
        snippet="Mechanistic interpretability proofs.",
        score=0.99,
        domain="arxiv.org",
    )
    client.set_query_results("safety", [special_hit])

    # Query matching substring
    res = await client.search(SearchQuery(query="AI safety alignment", max_results=5))
    assert len(res) == 1
    assert res[0].title == "Specific AI Safety Paper"

    # Fallback query
    fallback_res = await client.search(
        SearchQuery(query="unrelated query", max_results=1)
    )
    assert len(fallback_res) == 1
    assert fallback_res[0].title == "Sample Research Paper"

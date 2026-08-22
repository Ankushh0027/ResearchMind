"""Unit tests for LLM and Search adapter request/response contracts."""

import pytest
from pydantic import ValidationError

from app.adapters.llm.base import LLMRequest, LLMResponse, ToolCall
from app.adapters.search.base import SearchHit, SearchQuery


def test_llm_request_and_response_validation() -> None:
    """Verify LLMRequest and LLMResponse schema validation."""
    req = LLMRequest(
        system_prompt="You are a research analyst.",
        user_prompt="Summarize the core claim.",
        temperature=0.2,
        max_tokens=500,
    )
    assert req.temperature == 0.2
    assert req.max_tokens == 500

    # Negative tokens rejected
    with pytest.raises(ValidationError):
        LLMRequest(user_prompt="Query", max_tokens=-10)

    # Empty user prompt rejected
    with pytest.raises(ValidationError):
        LLMRequest(user_prompt="")

    tool_call = ToolCall(
        tool_name="web_search",
        arguments={"query": "quantum computing breakthroughs 2026"},
    )
    resp = LLMResponse(
        content="I will search for recent breakthroughs.",
        tool_calls=(tool_call,),
        prompt_tokens=30,
        completion_tokens=20,
        total_tokens=50,
        model_name="test-llm-v1",
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].tool_name == "web_search"
    assert resp.total_tokens == 50


def test_search_query_and_hit_validation() -> None:
    """Verify SearchQuery and SearchHit constraints."""
    query = SearchQuery(
        query="graph neural networks drug discovery",
        max_results=10,
        filters={"domain": "arxiv.org"},
    )
    assert query.max_results == 10
    assert query.filters["domain"] == "arxiv.org"

    # max_results boundary checks
    with pytest.raises(ValidationError):
        SearchQuery(query="Test", max_results=0)  # ge=1

    with pytest.raises(ValidationError):
        SearchQuery(query="Test", max_results=100)  # le=50

    hit = SearchHit(
        url="https://nature.com/articles/s41586-026-00000",
        title="Novel Deep Learning for Molecular Design",
        snippet="A comprehensive benchmark across 100k target compounds.",
        score=0.98,
        domain="nature.com",
        authors=("Dr. A. Smith",),
        publication_date="2026-02-01",
    )
    assert hit.score == 0.98
    assert hit.domain == "nature.com"

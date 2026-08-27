"""Unit tests for TavilySearchAdapter."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)
from app.adapters.search.tavily import (
    TavilySearchAdapter,
    _extract_domain,
    _is_retryable_search_error,
)


class TestTavilySearchAdapter:
    """Test suite for TavilySearchAdapter operations and reliability."""

    def test_protocol_conformance(self) -> None:
        """TavilySearchAdapter must satisfy SearchClientProtocol."""
        adapter = TavilySearchAdapter(api_key="test-key")
        assert isinstance(adapter, SearchClientProtocol)

    def test_missing_api_key_raises(self) -> None:
        """Missing API key when no client injected must raise ValueError."""
        adapter = TavilySearchAdapter(api_key="")
        query = SearchQuery(query="quantum computing")
        with pytest.raises(ValueError) as exc_info:
            import asyncio

            asyncio.run(adapter.search(query))
        assert "TAVILY_API_KEY is required" in str(exc_info.value)

    def test_extract_domain_helper(self) -> None:
        """Domain extractor should parse hostnames cleanly."""
        assert (
            _extract_domain("https://www.nature.com/articles/123") == "www.nature.com"
        )
        assert _extract_domain("http://arxiv.org/abs/2301.0001") == "arxiv.org"
        assert _extract_domain("invalid-url") == ""

    @pytest.mark.asyncio
    async def test_search_normalization_with_injected_client(self) -> None:
        """Verify normalization of raw Tavily JSON payload into SearchHit instances."""
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": "transformer architectures",
            "results": [
                {
                    "title": "Attention Is All You Need",
                    "url": "https://arxiv.org/abs/1706.03762",
                    "content": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
                    "score": 0.98,
                    "published_date": "2017-06-12",
                },
                {
                    "title": "Transformer Survey",
                    "url": "https://example.org/survey",
                    "content": "A comprehensive overview of recent transformer advancements.",
                    "score": 0.85,
                },
            ],
        }
        mock_http.post = AsyncMock(return_value=mock_response)

        adapter = TavilySearchAdapter(
            api_key="tvly-mock-key",
            client=mock_http,
        )

        query = SearchQuery(query="transformer architectures", max_results=2)
        hits = await adapter.search(query)

        assert len(hits) == 2
        assert isinstance(hits[0], SearchHit)
        assert hits[0].title == "Attention Is All You Need"
        assert hits[0].url == "https://arxiv.org/abs/1706.03762"
        assert "dominant sequence" in hits[0].snippet
        assert hits[0].score == pytest.approx(0.98)
        assert hits[0].domain == "arxiv.org"
        assert hits[0].publication_date == "2017-06-12"

        assert hits[1].title == "Transformer Survey"
        assert hits[1].domain == "example.org"

    @pytest.mark.asyncio
    async def test_retry_on_429_and_eventual_success(self) -> None:
        """429 Rate Limit responses should trigger bounded retry with eventual success."""
        mock_http = MagicMock()
        call_count = 0

        async def _flaky_post(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                resp = MagicMock()
                resp.status_code = 429

                def raise_err() -> None:
                    req = MagicMock()
                    req.url = "https://api.tavily.com/search"
                    raise httpx.HTTPStatusError(
                        "Rate Limit Exceeded", request=req, response=resp
                    )

                resp.raise_for_status = raise_err
                raise httpx.HTTPStatusError(
                    "Rate Limit Exceeded", request=MagicMock(), response=resp
                )

            success_resp = MagicMock()
            success_resp.status_code = 200
            success_resp.json.return_value = {
                "results": [
                    {
                        "title": "Success Result",
                        "url": "https://example.com/ok",
                        "content": "Recovered from rate limit",
                    }
                ]
            }
            return success_resp

        mock_http.post = AsyncMock(side_effect=_flaky_post)

        adapter = TavilySearchAdapter(
            api_key="tvly-test",
            max_retries=3,
            initial_retry_delay_seconds=0.01,
            client=mock_http,
        )

        hits = await adapter.search(SearchQuery(query="test"))
        assert len(hits) == 1
        assert hits[0].title == "Success Result"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_permanent_401_fails_fast(self) -> None:
        """401 Unauthorized errors should fail immediately without retrying."""
        mock_http = MagicMock()

        resp = MagicMock()
        resp.status_code = 401

        def raise_auth() -> None:
            raise httpx.HTTPStatusError(
                "Invalid API Key", request=MagicMock(), response=resp
            )

        resp.raise_for_status = raise_auth
        mock_http.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Invalid API Key", request=MagicMock(), response=resp
            )
        )

        adapter = TavilySearchAdapter(
            api_key="invalid-key",
            max_retries=3,
            initial_retry_delay_seconds=0.01,
            client=mock_http,
        )

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.search(SearchQuery(query="test"))

        assert mock_http.post.call_count == 1

    def test_error_classification(self) -> None:
        """Verify retryable vs permanent error helper."""
        assert _is_retryable_search_error(TimeoutError("Search timeout")) is True

        class MockStatusErr(Exception):
            def __init__(self, code: int) -> None:
                self.status_code = code

        assert _is_retryable_search_error(MockStatusErr(429)) is True
        assert _is_retryable_search_error(MockStatusErr(503)) is True
        assert _is_retryable_search_error(MockStatusErr(401)) is False
        assert _is_retryable_search_error(MockStatusErr(403)) is False

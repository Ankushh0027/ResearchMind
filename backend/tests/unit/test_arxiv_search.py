"""Unit tests for ArxivSearchAdapter."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.adapters.search.arxiv import (
    ArxivSearchAdapter,
    _clean_text,
    _is_retryable_arxiv_error,
)
from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)

SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">arXiv Query: search_query=all:quantum</title>
  <id>http://arxiv.org/api/123</id>
  <updated>2026-02-01T00:00:00Z</updated>
  <entry>
    <id>http://arxiv.org/abs/2301.01234v1</id>
    <published>2023-01-05T18:00:00Z</published>
    <updated>2023-01-05T18:00:00Z</updated>
    <title> Quantum Error Correction
    in Scalable Architectures </title>
    <summary> We demonstrate fault-tolerant quantum memory using surface codes
    with physical error rates below threshold. </summary>
    <author>
      <name>Alice Johnson</name>
    </author>
    <author>
      <name>Bob Smith</name>
    </author>
    <link href="http://arxiv.org/abs/2301.01234v1" rel="alternate" type="text/html"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.05678v1</id>
    <published>2023-01-10T12:00:00Z</published>
    <title>Topological Quantum Matter</title>
    <summary>A review of Majorana zero modes and topological phases.</summary>
    <author>
      <name>Carol Davis</name>
    </author>
  </entry>
</feed>
"""


class TestArxivSearchAdapter:
    """Test suite for ArxivSearchAdapter XML parsing, normalization, and retries."""

    def test_protocol_conformance(self) -> None:
        """ArxivSearchAdapter must satisfy SearchClientProtocol."""
        adapter = ArxivSearchAdapter()
        assert isinstance(adapter, SearchClientProtocol)

    def test_clean_text_helper(self) -> None:
        """Text cleaner should collapse multiple whitespace characters and newlines."""
        assert (
            _clean_text("  Title   with \n newlines \t and spaces  ")
            == "Title with newlines and spaces"
        )
        assert _clean_text(None) == ""

    @pytest.mark.asyncio
    async def test_search_and_xml_atom_parsing(self) -> None:
        """Verify parsing of standard arXiv Atom XML response feed into SearchHit instances."""
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_ARXIV_XML
        mock_http.get = AsyncMock(return_value=mock_response)

        adapter = ArxivSearchAdapter(client=mock_http)
        query = SearchQuery(query="quantum error correction", max_results=2)

        hits = await adapter.search(query)

        assert len(hits) == 2
        assert isinstance(hits[0], SearchHit)
        assert hits[0].title == "Quantum Error Correction in Scalable Architectures"
        assert hits[0].url == "https://arxiv.org/abs/2301.01234v1"
        assert "fault-tolerant quantum memory" in hits[0].snippet
        assert hits[0].authors == ("Alice Johnson", "Bob Smith")
        assert hits[0].domain == "arxiv.org"
        assert hits[0].publication_date == "2023-01-05T18:00:00Z"
        assert hits[0].score == 1.0

        assert hits[1].title == "Topological Quantum Matter"
        assert hits[1].authors == ("Carol Davis",)
        assert hits[1].score < 1.0

    @pytest.mark.asyncio
    async def test_empty_and_malformed_xml_handling(self) -> None:
        """Malformed or empty XML should return an empty list without raising exceptions."""
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<not_valid_xml><entry></not_valid_xml>"
        mock_http.get = AsyncMock(return_value=mock_response)

        adapter = ArxivSearchAdapter(client=mock_http)
        hits = await adapter.search(SearchQuery(query="broken xml"))
        assert hits == []

    @pytest.mark.asyncio
    async def test_retry_on_503_and_recovery(self) -> None:
        """Transient 503 Service Unavailable errors should trigger bounded retry."""
        mock_http = MagicMock()
        call_count = 0

        async def _flaky_get(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                resp = MagicMock()
                resp.status_code = 503

                def raise_err() -> None:
                    raise httpx.HTTPStatusError(
                        "Service Unavailable", request=MagicMock(), response=resp
                    )

                resp.raise_for_status = raise_err
                raise httpx.HTTPStatusError(
                    "Service Unavailable", request=MagicMock(), response=resp
                )

            success_resp = MagicMock()
            success_resp.status_code = 200
            success_resp.text = SAMPLE_ARXIV_XML
            return success_resp

        mock_http.get = AsyncMock(side_effect=_flaky_get)

        adapter = ArxivSearchAdapter(
            max_retries=2,
            initial_retry_delay_seconds=0.01,
            client=mock_http,
        )

        hits = await adapter.search(SearchQuery(query="test"))
        assert len(hits) == 2
        assert call_count == 2

    def test_error_classification(self) -> None:
        """Verify retry classification for arXiv errors."""
        assert _is_retryable_arxiv_error(TimeoutError("arXiv timeout")) is True

        class MockErr(Exception):
            def __init__(self, code: int) -> None:
                self.status_code = code

        assert _is_retryable_arxiv_error(MockErr(503)) is True
        assert _is_retryable_arxiv_error(MockErr(429)) is True
        assert _is_retryable_arxiv_error(MockErr(404)) is False

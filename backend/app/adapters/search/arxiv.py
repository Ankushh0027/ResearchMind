"""arXiv academic search adapter implementing SearchClientProtocol using arXiv's Atom API."""

import asyncio
import logging
import random
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import httpx

from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)

logger = logging.getLogger("researchmind.adapters.search.arxiv")

R = TypeVar("R")
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _is_retryable_arxiv_error(exc: Exception) -> bool:
    """Determine whether an arXiv query error is transient."""
    if isinstance(
        exc,
        (
            TimeoutError,
            asyncio.TimeoutError,
            httpx.TimeoutException,
            httpx.NetworkError,
        ),
    ):
        return True

    status_code = getattr(exc, "status_code", None)
    if status_code is None and hasattr(exc, "response") and exc.response is not None:
        status_code = getattr(exc.response, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", getattr(exc, "status", None))

    if status_code in (429, 500, 502, 503, 504):
        return True

    err_str = str(exc).upper()
    return any(
        m in err_str
        for m in ("429", "500", "502", "503", "504", "TIMEOUT", "CONNECTION")
    )


def _clean_text(raw_text: str | None) -> str:
    """Remove redundant internal newlines and normalize whitespace."""
    if not raw_text:
        return ""
    return re.sub(r"\s+", " ", raw_text).strip()


class ArxivSearchAdapter(SearchClientProtocol):
    """Production arXiv academic search adapter implementing SearchClientProtocol."""

    def __init__(
        self,
        api_url: str = "https://export.arxiv.org/api/query",
        request_timeout_seconds: float = 20.0,
        max_retries: int = 3,
        initial_retry_delay_seconds: float = 1.0,
        max_retry_delay_seconds: float = 10.0,
        client: Any = None,
    ) -> None:
        self.api_url = api_url.strip() or "https://export.arxiv.org/api/query"
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.max_retries = max(0, max_retries)
        self.initial_retry_delay_seconds = max(0.01, initial_retry_delay_seconds)
        self.max_retry_delay_seconds = max(
            self.initial_retry_delay_seconds, max_retry_delay_seconds
        )
        self._client = client

    async def _execute_with_retry(
        self,
        operation_name: str,
        func: Callable[[], Coroutine[Any, Any, R]],
    ) -> R:
        """Execute arXiv request with bounded retry and exponential backoff."""
        attempt = 0
        while True:
            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    return await func()
            except asyncio.CancelledError:
                logger.info("arXiv search operation '%s' cancelled.", operation_name)
                raise
            except Exception as exc:
                if not _is_retryable_arxiv_error(exc) or attempt >= self.max_retries:
                    logger.error(
                        "arXiv search '%s' failed (attempt %d/%d): %s",
                        operation_name,
                        attempt + 1,
                        self.max_retries + 1,
                        type(exc).__name__,
                    )
                    raise

                base_delay = min(
                    self.max_retry_delay_seconds,
                    self.initial_retry_delay_seconds * (2**attempt),
                )
                jitter = random.uniform(0.8, 1.2)
                delay = base_delay * jitter

                logger.warning(
                    "arXiv search '%s' encountered transient error on attempt %d/%d. Retrying in %.2fs...",
                    operation_name,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )

                await asyncio.sleep(delay)
                attempt += 1

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute academic query against the arXiv API and return normalized search hits."""
        client = self._client

        # Construct sanitized search query string
        clean_q = _clean_text(query.query)
        params: dict[str, Any] = {
            "search_query": f"all:{clean_q}",
            "start": 0,
            "max_results": query.max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        if query.filters and "category" in query.filters:
            params["search_query"] = (
                f"cat:{query.filters['category']} AND all:{clean_q}"
            )

        async def _call() -> Any:
            if client is not None:
                if hasattr(client, "get") or hasattr(client, "request"):
                    res = client.get(self.api_url, params=params)
                    resp = await res if asyncio.iscoroutine(res) else res
                    if (
                        hasattr(resp, "status_code")
                        and resp.status_code != 200
                        and hasattr(resp, "raise_for_status")
                    ):
                        resp.raise_for_status()
                    return resp
                if hasattr(client, "search"):
                    res = client.search(query)
                    return await res if asyncio.iscoroutine(res) else res

            async with httpx.AsyncClient(
                timeout=self.request_timeout_seconds
            ) as http_client:
                resp = await http_client.get(self.api_url, params=params)
                if resp.status_code != 200:
                    resp.raise_for_status()
                return resp.text

        raw_response = await self._execute_with_retry(f"search('{query.query}')", _call)

        # Injected mock might return list of SearchHit directly
        if isinstance(raw_response, list):
            return [
                item if isinstance(item, SearchHit) else SearchHit.model_validate(item)
                for item in raw_response
            ][: query.max_results]

        xml_content = getattr(raw_response, "text", raw_response)
        if not isinstance(xml_content, str) or not xml_content.strip():
            return []

        return self._parse_atom_feed(xml_content, max_results=query.max_results)

    def _parse_atom_feed(self, xml_content: str, max_results: int) -> list[SearchHit]:
        """Parse XML Atom response feed into SearchHit models."""
        hits: list[SearchHit] = []
        try:
            root = ET.fromstring(xml_content)
        except Exception as e:
            logger.warning("Failed to parse arXiv Atom XML feed: %s", e)
            return []

        entries = root.findall(f"{ATOM_NS}entry")
        if not entries:
            # Try without namespace prefix fallback
            entries = root.findall("entry")

        for idx, entry in enumerate(entries):
            if idx >= max_results:
                break

            # URL / ID
            id_elem = entry.find(f"{ATOM_NS}id")
            if id_elem is None:
                id_elem = entry.find("id")
            raw_id = (
                id_elem.text.strip() if id_elem is not None and id_elem.text else ""
            )

            # Check alternate link
            link_elem = entry.find(f"{ATOM_NS}link[@rel='alternate']")
            if link_elem is not None and link_elem.get("href"):
                url = link_elem.get("href", "").strip()
            else:
                url = raw_id

            if not url:
                continue

            # Ensure https://
            if url.startswith("http://"):
                url = "https://" + url[7:]

            # Title
            title_elem = entry.find(f"{ATOM_NS}title")
            if title_elem is None:
                title_elem = entry.find("title")
            title = _clean_text(title_elem.text) if title_elem is not None else url

            # Summary / Abstract
            summary_elem = entry.find(f"{ATOM_NS}summary")
            if summary_elem is None:
                summary_elem = entry.find("summary")
            snippet = _clean_text(summary_elem.text) if summary_elem is not None else ""

            # Authors
            authors: list[str] = []
            author_elems = entry.findall(f"{ATOM_NS}author") or entry.findall("author")
            for a in author_elems:
                name_elem = a.find(f"{ATOM_NS}name")
                if name_elem is None:
                    name_elem = a.find("name")
                if name_elem is not None and name_elem.text and name_elem.text.strip():
                    authors.append(_clean_text(name_elem.text))

            # Published Date
            pub_elem = entry.find(f"{ATOM_NS}published")
            if pub_elem is None:
                pub_elem = entry.find("published")
            pub_date = _clean_text(pub_elem.text) if pub_elem is not None else None

            # Rank score decaying slightly by position
            score = max(0.5, round(1.0 - (idx * 0.05), 2))

            hits.append(
                SearchHit(
                    url=url,
                    title=title or "arXiv Paper",
                    snippet=snippet,
                    score=score,
                    domain="arxiv.org",
                    authors=tuple(authors),
                    publication_date=pub_date,
                )
            )

        return hits


__all__ = [
    "ArxivSearchAdapter",
    "_clean_text",
    "_is_retryable_arxiv_error",
]

"""Tavily search client adapter implementing SearchClientProtocol."""

import asyncio
import logging
import random
import urllib.parse
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import httpx

from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)

logger = logging.getLogger("researchmind.adapters.search.tavily")

R = TypeVar("R")


def _is_retryable_search_error(exc: Exception) -> bool:
    """Determine whether a search exception represents a transient failure."""
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

    if status_code in (400, 401, 403, 404):
        return False
    if status_code in (429, 500, 502, 503, 504):
        return True

    err_str = str(exc).upper()
    if any(
        m in err_str
        for m in ("400", "401", "403", "404", "UNAUTHORIZED", "FORBIDDEN", "INVALID")
    ):
        return False
    return any(
        m in err_str
        for m in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "RATE_LIMIT",
            "TIMEOUT",
            "CONNECTION",
        )
    )


def _extract_domain(url: str) -> str:
    """Extract clean domain name from a URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


class TavilySearchAdapter(SearchClientProtocol):
    """Production Tavily Web Search API adapter implementing SearchClientProtocol."""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str = "https://api.tavily.com/search",
        request_timeout_seconds: float = 15.0,
        max_retries: int = 3,
        initial_retry_delay_seconds: float = 1.0,
        max_retry_delay_seconds: float = 10.0,
        client: Any = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.api_url = api_url.strip() or "https://api.tavily.com/search"
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
        """Execute search operation with bounded exponential backoff on transient errors."""
        attempt = 0
        while True:
            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    return await func()
            except asyncio.CancelledError:
                logger.info("Tavily search operation '%s' cancelled.", operation_name)
                raise
            except Exception as exc:
                if not _is_retryable_search_error(exc) or attempt >= self.max_retries:
                    logger.error(
                        "Tavily search '%s' failed (attempt %d/%d, retryable=%s): %s",
                        operation_name,
                        attempt + 1,
                        self.max_retries + 1,
                        _is_retryable_search_error(exc),
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
                    "Tavily search '%s' transient failure on attempt %d/%d. Retrying in %.2fs...",
                    operation_name,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )

                await asyncio.sleep(delay)
                attempt += 1

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute web search query via Tavily Search API."""
        if not self.api_key and self._client is None:
            raise ValueError(
                "TAVILY_API_KEY is required for TavilySearchAdapter when no client is injected."
            )

        client = self._client

        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query.query,
            "max_results": query.max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        if query.filters:
            payload.update(query.filters)

        async def _call() -> Any:
            if client is not None:
                if hasattr(client, "post") or hasattr(client, "request"):
                    res = client.post(self.api_url, json=payload)
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
                resp = await http_client.post(self.api_url, json=payload)
                if resp.status_code != 200:
                    resp.raise_for_status()
                return resp.json()

        raw_response = await self._execute_with_retry(f"search('{query.query}')", _call)

        # Handle direct list of SearchHit (e.g. from mock client)
        if isinstance(raw_response, list):
            return [
                item if isinstance(item, SearchHit) else SearchHit.model_validate(item)
                for item in raw_response
            ][: query.max_results]

        # Extract data payload from Response object or dict
        if hasattr(raw_response, "json"):
            data = raw_response.json()
        elif isinstance(raw_response, dict):
            data = raw_response
        else:
            data = {}

        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            return []

        hits: list[SearchHit] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            title = str(item.get("title", "")).strip() or url
            snippet = (
                str(item.get("content", "")).strip()
                or str(item.get("snippet", "")).strip()
            )
            score_val = item.get("score")
            try:
                score = (
                    max(0.0, min(1.0, float(score_val)))
                    if score_val is not None
                    else 1.0
                )
            except (ValueError, TypeError):
                score = 1.0

            domain = _extract_domain(url)
            pub_date = item.get("published_date")

            hits.append(
                SearchHit(
                    url=url,
                    title=title,
                    snippet=snippet,
                    score=score,
                    domain=domain,
                    publication_date=str(pub_date) if pub_date else None,
                )
            )

        return hits[: query.max_results]


__all__ = [
    "TavilySearchAdapter",
    "_is_retryable_search_error",
]

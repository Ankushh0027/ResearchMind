"""Typed HTTP and Server-Sent Events client for interacting with ResearchMind API."""

import json
import os
import re
import warnings
from collections.abc import Iterator
from typing import Any

import httpx
from starlette.exceptions import StarletteDeprecationWarning

SECRET_PATTERNS = [
    re.compile(r"(AIza[0-9A-Za-z\-_]{35})"),
    re.compile(r"(sk-[A-Za-z0-9\-_]{20,})"),
    re.compile(r"(key-[0-9a-zA-Z]{32})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*)"),
]


def redact_secrets(text: str) -> str:
    """Scrub sensitive tokens or API credentials from error messages."""
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


class CLIClientError(Exception):
    """Exception raised for client-side API interaction failures."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        clean_msg = redact_secrets(message)
        super().__init__(clean_msg)
        self.message = clean_msg
        self.status_code = status_code
        self.error_code = error_code or "CLIENT_ERROR"
        self.details = details or {}


class ResearchMindClient:
    """HTTP and SSE client communicating with the ResearchMind API Gateway."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        app: Any = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("RESEARCHMIND_API_URL")
            or "http://localhost:8080"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("RESEARCHMIND_API_KEY")
        self.timeout = timeout
        self._transport = transport
        self._app = app

    def _get_headers(self) -> dict[str, str]:
        headers = {"User-Agent": "ResearchMind-CLI/0.1.0"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _create_http_client(self) -> httpx.Client:
        if self._app is not None:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
                from starlette.testclient import TestClient

                return TestClient(
                    app=self._app,
                    base_url=self.base_url,
                    headers=self._get_headers(),
                )

        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "headers": self._get_headers(),
            "timeout": self.timeout,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def health(self) -> dict[str, Any]:
        """Perform public system health check."""
        try:
            with self._create_http_client() as client:
                res = client.get("/healthz")
                if res.status_code != 200:
                    raise CLIClientError(
                        f"Health check failed with HTTP {res.status_code}: {res.text}",
                        status_code=res.status_code,
                    )
                data: dict[str, Any] = res.json()
                return data
        except httpx.RequestError as e:
            raise CLIClientError(
                f"Could not connect to ResearchMind API at '{self.base_url}': {e}"
            ) from e

    def submit_run(
        self,
        query: str,
        domain_tags: list[str] | None = None,
        constraints: dict[str, Any] | None = None,
        max_subtasks: int = 10,
    ) -> dict[str, Any]:
        """Submit a new research inquiry."""
        payload: dict[str, Any] = {
            "query": query,
            "domain_tags": domain_tags or [],
            "constraints": constraints or {},
            "max_subtasks": max_subtasks,
        }
        try:
            with self._create_http_client() as client:
                res = client.post("/api/v1/runs", json=payload)
                if res.status_code in (200, 201):
                    data: dict[str, Any] = res.json()
                    return data
                self._raise_for_error(res)
        except httpx.RequestError as e:
            raise CLIClientError(f"Failed to submit research run: {e}") from e
        return {}

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Fetch details, metrics, and compiled deliverable for a run."""
        try:
            with self._create_http_client() as client:
                res = client.get(f"/api/v1/runs/{run_id}")
                if res.status_code == 200:
                    data: dict[str, Any] = res.json()
                    return data
                self._raise_for_error(res)
        except httpx.RequestError as e:
            raise CLIClientError(f"Failed to fetch run '{run_id}': {e}") from e
        return {}

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Request cancellation of an active run."""
        try:
            with self._create_http_client() as client:
                res = client.post(f"/api/v1/runs/{run_id}/cancel")
                if res.status_code == 200:
                    data: dict[str, Any] = res.json()
                    return data
                self._raise_for_error(res)
        except httpx.RequestError as e:
            raise CLIClientError(f"Failed to cancel run '{run_id}': {e}") from e
        return {}

    def stream_events(self, run_id: str) -> Iterator[tuple[str, dict[str, Any] | str]]:
        """Subscribe to real-time Server-Sent Events (SSE) stream."""
        try:
            with (
                self._create_http_client() as client,
                client.stream(
                    "GET", f"/api/v1/runs/{run_id}/events", timeout=None
                ) as response,
            ):
                if response.status_code != 200:
                    self._raise_for_error(response)

                current_event = "message"
                current_data: list[str] = []

                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        if current_data:
                            data_str = "\n".join(current_data)
                            try:
                                parsed = json.loads(data_str)
                            except Exception:
                                parsed = data_str
                            yield (current_event, parsed)
                            current_event = "message"
                            current_data = []
                        continue

                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        current_data.append(line[5:].strip())

                if current_data:
                    data_str = "\n".join(current_data)
                    try:
                        parsed = json.loads(data_str)
                    except Exception:
                        parsed = data_str
                    yield (current_event, parsed)

        except httpx.RequestError as e:
            raise CLIClientError(
                f"SSE stream disconnected for run '{run_id}': {e}"
            ) from e

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """List metadata for all durable artifacts belonging to a run."""
        try:
            with self._create_http_client() as client:
                res = client.get(f"/api/v1/runs/{run_id}/artifacts")
                if res.status_code == 200:
                    data: list[dict[str, Any]] = res.json()
                    return data
                self._raise_for_error(res)
        except httpx.RequestError as e:
            raise CLIClientError(
                f"Failed to list artifacts for run '{run_id}': {e}"
            ) from e
        return []

    def download_artifact(
        self, run_id: str, artifact_id: str, target_file_path: str
    ) -> int:
        """Stream an artifact binary/text payload directly to disk."""
        total_bytes = 0
        try:
            with (
                self._create_http_client() as client,
                client.stream(
                    "GET", f"/api/v1/runs/{run_id}/artifacts/{artifact_id}"
                ) as response,
            ):
                if response.status_code != 200:
                    self._raise_for_error(response)

                os.makedirs(
                    os.path.dirname(os.path.abspath(target_file_path)), exist_ok=True
                )
                with open(target_file_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        total_bytes += len(chunk)
            return total_bytes
        except httpx.RequestError as e:
            raise CLIClientError(
                f"Failed to download artifact '{artifact_id}': {e}"
            ) from e

    def _raise_for_error(self, response: httpx.Response) -> None:
        """Parse structured API error payload or raise with status description."""
        status = response.status_code
        try:
            error_data = response.json()
            if isinstance(error_data, dict):
                detail = error_data.get("detail", error_data)
                if isinstance(detail, dict):
                    err_code = detail.get("error_code", f"HTTP_{status}")
                    msg = detail.get("message", response.text)
                    raise CLIClientError(
                        msg, status_code=status, error_code=err_code, details=detail
                    )
                elif isinstance(detail, str):
                    raise CLIClientError(
                        detail, status_code=status, error_code=f"HTTP_{status}"
                    )
        except json.JSONDecodeError:
            pass

        if status == 401:
            raise CLIClientError(
                "Authentication failed: Missing or invalid API key.",
                status_code=401,
                error_code="UNAUTHORIZED",
            )
        elif status == 404:
            raise CLIClientError(
                "Resource not found.", status_code=404, error_code="NOT_FOUND"
            )
        elif status == 429:
            raise CLIClientError(
                "Rate limit exceeded. Please retry after delay.",
                status_code=429,
                error_code="RATE_LIMIT_EXCEEDED",
            )
        elif status >= 500:
            raise CLIClientError(
                f"Internal server error (HTTP {status}): {response.text}",
                status_code=status,
                error_code="SERVER_ERROR",
            )

        raise CLIClientError(
            f"API request failed with HTTP {status}: {response.text}",
            status_code=status,
        )


__all__ = [
    "CLIClientError",
    "ResearchMindClient",
    "redact_secrets",
]

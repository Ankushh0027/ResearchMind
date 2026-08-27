"""Production Qdrant vector store adapter implementing VectorStoreProtocol."""

import asyncio
import logging
import random
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from pydantic import ValidationError

from app.common.errors import EvidenceValidationError, ResearchMindError
from app.rag.embeddings import validate_dense_vector
from app.rag.protocols import (
    VectorPoint,
    VectorSearchResult,
    VectorStoreProtocol,
)

logger = logging.getLogger("researchmind.rag.qdrant")

R = TypeVar("R")
DEFAULT_QDRANT_DIMENSION = 768


def _is_retryable_error(exc: Exception) -> bool:
    """Determine whether an exception represents a transient, retryable Qdrant/network failure."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
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
    non_retryable_markers = (
        "400",
        "401",
        "403",
        "404",
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "API_KEY_INVALID",
    )
    if any(marker in err_str for marker in non_retryable_markers):
        return False

    retryable_markers = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "CONNECTION",
        "TIMEOUT",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "INTERNAL",
        "RESET",
        "BROKEN_PIPE",
    )
    return any(marker in err_str for marker in retryable_markers)


def _to_valid_qdrant_id(point_id: str) -> str:
    """Convert an arbitrary string identifier into a valid UUID string for Qdrant storage."""
    try:
        # Check if already a valid UUID string
        val = uuid.UUID(point_id)
        return str(val)
    except (ValueError, AttributeError):
        # Generate a deterministic UUID5 from string
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, point_id))


class QdrantVectorStore(VectorStoreProtocol):
    """Production-grade Qdrant dense vector store implementing VectorStoreProtocol."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        dimension: int = DEFAULT_QDRANT_DIMENSION,
        distance: str = "Cosine",
        request_timeout_seconds: float = 30.0,
        max_retries: int = 3,
        initial_retry_delay_seconds: float = 0.5,
        max_retry_delay_seconds: float = 5.0,
        client: Any = None,
    ) -> None:
        if (
            not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension <= 0
        ):
            raise EvidenceValidationError(
                f"dimension must be a positive integer, got {dimension}",
                {"dimension": dimension},
            )

        self.url = url.strip() or "http://localhost:6333"
        self.api_key = api_key
        self.dimension = dimension
        self.distance = distance
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.max_retries = max(0, max_retries)
        self.initial_retry_delay_seconds = max(0.01, initial_retry_delay_seconds)
        self.max_retry_delay_seconds = max(
            self.initial_retry_delay_seconds, max_retry_delay_seconds
        )
        self._client = client
        self._known_collections: set[str] = set()

    def _get_distance_metric(self) -> Any:
        """Resolve Qdrant distance metric enum."""
        try:
            from qdrant_client import models

            dist_lower = self.distance.lower()
            if dist_lower == "cosine":
                return models.Distance.COSINE
            if dist_lower in ("euclid", "euclidean"):
                return models.Distance.EUCLID
            if dist_lower == "dot":
                return models.Distance.DOT
            return models.Distance.COSINE
        except ImportError:
            return "Cosine"

    def _get_client(self) -> Any:
        """Resolve or lazily initialize the AsyncQdrantClient."""
        if self._client is not None:
            return self._client

        try:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(
                url=self.url,
                api_key=self.api_key if self.api_key else None,
                timeout=int(self.request_timeout_seconds),
            )
            return self._client
        except ImportError as e:
            raise RuntimeError(
                "qdrant-client is required for QdrantVectorStore. "
                "Install with: pip install qdrant-client"
            ) from e

    async def _execute_with_retry(
        self,
        operation_name: str,
        func: Callable[[], Coroutine[Any, Any, R]],
    ) -> R:
        """Execute an asynchronous Qdrant operation with timeout and bounded exponential backoff."""
        attempt = 0
        while True:
            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    return await func()
            except asyncio.CancelledError:
                logger.info("Qdrant operation '%s' was cancelled.", operation_name)
                raise
            except Exception as exc:
                if isinstance(
                    exc,
                    (
                        ValidationError,
                        EvidenceValidationError,
                        TypeError,
                        ValueError,
                    ),
                ) and not isinstance(exc, ResearchMindError):
                    raise

                if not _is_retryable_error(exc) or attempt >= self.max_retries:
                    logger.error(
                        "Qdrant operation '%s' failed (attempt %d/%d, retryable=%s): %s",
                        operation_name,
                        attempt + 1,
                        self.max_retries + 1,
                        _is_retryable_error(exc),
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
                    "Qdrant operation '%s' encountered transient error on attempt %d/%d: %s. Retrying in %.2fs...",
                    operation_name,
                    attempt + 1,
                    self.max_retries,
                    type(exc).__name__,
                    delay,
                )

                await asyncio.sleep(delay)
                attempt += 1

    async def ensure_collection(self, collection_name: str) -> None:
        """Verify that a named collection exists in Qdrant; create it if missing."""
        clean_name = collection_name.strip()
        if not clean_name:
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )

        if clean_name in self._known_collections:
            return

        client = self._get_client()

        async def _check_and_create() -> None:
            # Check if collection exists
            exists = False
            if hasattr(client, "collection_exists"):
                res = client.collection_exists(clean_name)
                exists = await res if asyncio.iscoroutine(res) else res
            elif hasattr(client, "get_collection"):
                try:
                    res = client.get_collection(clean_name)
                    if asyncio.iscoroutine(res):
                        await res
                    exists = True
                except Exception:
                    exists = False

            if not exists:
                vectors_config: Any
                try:
                    from qdrant_client import models

                    vectors_config = models.VectorParams(
                        size=self.dimension,
                        distance=self._get_distance_metric(),
                    )
                except (ImportError, AttributeError):
                    vectors_config = {
                        "size": self.dimension,
                        "distance": self.distance,
                    }

                if hasattr(client, "create_collection"):
                    call = client.create_collection(
                        collection_name=clean_name,
                        vectors_config=vectors_config,
                    )
                    if asyncio.iscoroutine(call):
                        await call

            self._known_collections.add(clean_name)

        await self._execute_with_retry(
            f"ensure_collection({clean_name})", _check_and_create
        )

    async def upsert_vectors(
        self, collection_name: str, points: list[VectorPoint]
    ) -> int:
        """Upsert dense vector points into a named collection, returning count of upserted items."""
        clean_name = collection_name.strip()
        if not clean_name:
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )

        if points is None or not isinstance(points, list):
            raise TypeError("points must be a list of VectorPoint instances")

        if not points:
            return 0

        # Validate all points before submitting
        validated_qdrant_points: list[Any] = []
        for pt in points:
            if not isinstance(pt, VectorPoint):
                raise TypeError(f"Expected VectorPoint, got {type(pt).__name__}")
            vec = validate_dense_vector(pt.vector, expected_dimension=self.dimension)

            payload = dict(pt.payload or {})
            payload["point_id"] = pt.point_id

            point_struct: Any
            try:
                from qdrant_client import models

                point_struct = models.PointStruct(
                    id=_to_valid_qdrant_id(pt.point_id),
                    vector=list(vec),
                    payload=payload,
                )
            except (ImportError, AttributeError):
                point_struct = {
                    "id": _to_valid_qdrant_id(pt.point_id),
                    "vector": list(vec),
                    "payload": payload,
                }
            validated_qdrant_points.append(point_struct)

        await self.ensure_collection(clean_name)
        client = self._get_client()

        async def _call_upsert() -> Any:
            if hasattr(client, "upsert"):
                call = client.upsert(
                    collection_name=clean_name,
                    points=validated_qdrant_points,
                )
                if asyncio.iscoroutine(call):
                    return await call
                return await asyncio.to_thread(
                    client.upsert,
                    collection_name=clean_name,
                    points=validated_qdrant_points,
                )
            raise RuntimeError(
                f"Injected client {type(client).__name__} does not support upsert."
            )

        await self._execute_with_retry(f"upsert_vectors({clean_name})", _call_upsert)
        return len(points)

    async def search_vectors(
        self,
        collection_name: str,
        query_vector: tuple[float, ...] | list[float],
        limit: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Perform nearest-neighbor similarity search against a named Qdrant collection."""
        clean_name = collection_name.strip()
        if not clean_name:
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )

        if limit <= 0:
            raise EvidenceValidationError(
                f"limit must be a positive integer, got {limit}",
                {"limit": limit},
            )

        validated_query = validate_dense_vector(
            query_vector, expected_dimension=self.dimension
        )

        client = self._get_client()

        # Build Qdrant filter condition if requested
        query_filter: Any = None
        if filter_metadata:
            try:
                from qdrant_client import models

                conditions: list[Any] = [
                    models.FieldCondition(
                        key=k,
                        match=models.MatchValue(value=v),
                    )
                    for k, v in filter_metadata.items()
                ]
                query_filter = models.Filter(must=conditions)
            except (ImportError, AttributeError):
                query_filter = filter_metadata

        async def _call_search() -> Any:
            # Modern Qdrant client search / query_points
            if hasattr(client, "search"):
                call = client.search(
                    collection_name=clean_name,
                    query_vector=list(validated_query),
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )
                if asyncio.iscoroutine(call):
                    return await call
                return await asyncio.to_thread(
                    client.search,
                    collection_name=clean_name,
                    query_vector=list(validated_query),
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )

            if hasattr(client, "query_points"):
                call = client.query_points(
                    collection_name=clean_name,
                    query=list(validated_query),
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )
                res = await call if asyncio.iscoroutine(call) else call
                return getattr(res, "points", res)

            raise RuntimeError(
                f"Injected client {type(client).__name__} does not support similarity search."
            )

        raw_results = await self._execute_with_retry(
            f"search_vectors({clean_name})", _call_search
        )

        results: list[VectorSearchResult] = []
        if isinstance(raw_results, list):
            for item in raw_results:
                payload = getattr(item, "payload", {}) or {}
                if isinstance(item, dict):
                    payload = item.get("payload", {})
                    score = float(item.get("score", 0.0))
                    point_id = payload.get("point_id", str(item.get("id", "")))
                else:
                    score = float(getattr(item, "score", 0.0))
                    point_id = payload.get("point_id", str(getattr(item, "id", "")))

                results.append(
                    VectorSearchResult(
                        point_id=point_id,
                        score=score,
                        payload=payload,
                    )
                )

        return results

    async def delete_collection(self, collection_name: str) -> None:
        """Delete a named vector collection in Qdrant."""
        clean_name = collection_name.strip()
        if not clean_name:
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )

        client = self._get_client()

        async def _call_delete() -> Any:
            if hasattr(client, "delete_collection"):
                call = client.delete_collection(clean_name)
                if asyncio.iscoroutine(call):
                    return await call
                return await asyncio.to_thread(client.delete_collection, clean_name)
            return None

        await self._execute_with_retry(f"delete_collection({clean_name})", _call_delete)
        self._known_collections.discard(clean_name)


__all__ = [
    "DEFAULT_QDRANT_DIMENSION",
    "QdrantVectorStore",
    "_to_valid_qdrant_id",
]

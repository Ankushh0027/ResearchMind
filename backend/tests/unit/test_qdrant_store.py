"""Unit tests for QdrantVectorStore adapter and factory constructors."""

import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.common.errors import EvidenceValidationError
from app.config.settings import AppSettings
from app.rag.factory import create_vector_store
from app.rag.protocols import (
    VectorPoint,
    VectorSearchResult,
    VectorStoreProtocol,
)
from app.rag.qdrant import (
    QdrantVectorStore,
    _is_retryable_error,
    _to_valid_qdrant_id,
)
from app.rag.store import InMemoryVectorStore


class FakeQdrantClient:
    """Deterministic in-memory fake for AsyncQdrantClient."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.vectors_configs: dict[str, Any] = {}
        self.created_collections: list[str] = []
        self.deleted_collections: list[str] = []
        self.upsert_calls: list[dict[str, Any]] = []

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    async def create_collection(
        self, collection_name: str, vectors_config: Any = None, **_kwargs: Any
    ) -> bool:
        self.collections[collection_name] = {}
        self.vectors_configs[collection_name] = vectors_config
        self.created_collections.append(collection_name)
        return True

    async def upsert(self, collection_name: str, points: list[Any]) -> Any:
        if collection_name not in self.collections:
            self.collections[collection_name] = {}
        col = self.collections[collection_name]
        for p in points:
            pid = getattr(p, "id", None) or (
                p.get("id") if isinstance(p, dict) else str(p)
            )
            col[str(pid)] = p
        self.upsert_calls.append({"collection": collection_name, "count": len(points)})
        return MagicMock(status="completed")

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
        query_filter: Any = None,
        with_payload: bool = True,
        **_kwargs: Any,
    ) -> list[Any]:
        col = self.collections.get(collection_name, {})
        results: list[Any] = []
        for pid, pt in col.items():
            payload = (
                (
                    getattr(pt, "payload", {})
                    if not isinstance(pt, dict)
                    else pt.get("payload", {})
                )
                if with_payload
                else {}
            )
            vec = (
                getattr(pt, "vector", [])
                if not isinstance(pt, dict)
                else pt.get("vector", [])
            )

            # Simple filter check if filter provided
            if query_filter is not None and hasattr(query_filter, "must"):
                match = True
                for cond in query_filter.must:
                    k = getattr(cond, "key", None)
                    match_val = getattr(cond, "match", None)
                    v = getattr(match_val, "value", None) if match_val else None
                    if k is not None and payload.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            # Cosine similarity calculation
            dot = sum(a * b for a, b in zip(query_vector, vec, strict=False))
            norm_a = math.sqrt(sum(a * a for a in query_vector))
            norm_b = math.sqrt(sum(b * b for b in vec))
            score = dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

            mock_point = MagicMock()
            mock_point.id = pid
            mock_point.score = round(score, 4)
            mock_point.payload = payload
            results.append(mock_point)

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    async def delete_collection(self, collection_name: str) -> bool:
        self.collections.pop(collection_name, None)
        self.deleted_collections.append(collection_name)
        return True


class TestQdrantVectorStore:
    """Test suite verifying QdrantVectorStore protocol conformance and operations."""

    def test_protocol_conformance(self) -> None:
        """QdrantVectorStore must satisfy VectorStoreProtocol."""
        store = QdrantVectorStore(dimension=768)
        assert isinstance(store, VectorStoreProtocol)

    def test_invalid_dimension_rejected(self) -> None:
        """Non-positive or non-integer dimensions must raise EvidenceValidationError."""
        with pytest.raises(EvidenceValidationError):
            QdrantVectorStore(dimension=0)
        with pytest.raises(EvidenceValidationError):
            QdrantVectorStore(dimension=-5)

    def test_id_mapping(self) -> None:
        """Deterministic UUIDs must be generated for arbitrary string point IDs."""
        valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
        assert _to_valid_qdrant_id(valid_uuid) == valid_uuid

        custom_id = "doc_chunk_01"
        mapped = _to_valid_qdrant_id(custom_id)
        assert mapped != custom_id
        # Must be deterministic
        assert _to_valid_qdrant_id(custom_id) == mapped

    @pytest.mark.asyncio
    async def test_upsert_and_search_flow(self) -> None:
        """Verify complete upsert and similarity search flow against fake Qdrant client."""
        fake_client = FakeQdrantClient()
        store = QdrantVectorStore(
            dimension=4,
            client=fake_client,
        )

        pts = [
            VectorPoint(
                point_id="pt_1",
                vector=(1.0, 0.0, 0.0, 0.0),
                payload={"run_id": "run_01", "topic": "ai"},
            ),
            VectorPoint(
                point_id="pt_2",
                vector=(0.0, 1.0, 0.0, 0.0),
                payload={"run_id": "run_01", "topic": "biology"},
            ),
            VectorPoint(
                point_id="pt_3",
                vector=(0.8, 0.2, 0.0, 0.0),
                payload={"run_id": "run_02", "topic": "ai"},
            ),
        ]

        count = await store.upsert_vectors("evidence_test", pts)
        assert count == 3
        assert "evidence_test" in fake_client.collections

        # Query for pt_1
        query_vec = (1.0, 0.0, 0.0, 0.0)
        results = await store.search_vectors("evidence_test", query_vec, limit=2)
        assert len(results) == 2
        assert isinstance(results[0], VectorSearchResult)
        assert results[0].point_id == "pt_1"
        assert results[0].score == pytest.approx(1.0, rel=1e-2)

        # Filter by run_id = run_02
        filtered = await store.search_vectors(
            "evidence_test",
            query_vec,
            limit=5,
            filter_metadata={"run_id": "run_02"},
        )
        assert len(filtered) == 1
        assert filtered[0].point_id == "pt_3"
        assert filtered[0].payload["topic"] == "ai"

    @pytest.mark.asyncio
    async def test_dimension_mismatch_rejected(self) -> None:
        """Vectors with mismatched dimensionality must be rejected."""
        fake_client = FakeQdrantClient()
        store = QdrantVectorStore(dimension=4, client=fake_client)

        pts = [
            VectorPoint(
                point_id="invalid_dim",
                vector=(1.0, 0.0),  # Dimension 2 instead of 4
                payload={},
            )
        ]
        with pytest.raises(EvidenceValidationError):
            await store.upsert_vectors("evidence_test", pts)

    @pytest.mark.asyncio
    async def test_nan_and_inf_vectors_rejected(self) -> None:
        """Vectors with NaN or Infinity must be rejected."""
        fake_client = FakeQdrantClient()
        store = QdrantVectorStore(dimension=2, client=fake_client)

        nan_pt = [
            VectorPoint(point_id="nan_pt", vector=(float("nan"), 1.0), payload={})
        ]
        with pytest.raises(EvidenceValidationError):
            await store.upsert_vectors("evidence_test", nan_pt)

        inf_pt = [
            VectorPoint(point_id="inf_pt", vector=(float("inf"), 1.0), payload={})
        ]
        with pytest.raises(EvidenceValidationError):
            await store.upsert_vectors("evidence_test", inf_pt)

    @pytest.mark.asyncio
    async def test_delete_collection(self) -> None:
        """Delete collection must remove the collection from the Qdrant client."""
        fake_client = FakeQdrantClient()
        store = QdrantVectorStore(dimension=4, client=fake_client)

        await store.ensure_collection("temp_col")
        assert "temp_col" in fake_client.collections

        await store.delete_collection("temp_col")
        assert "temp_col" not in fake_client.collections
        assert "temp_col" in fake_client.deleted_collections

    @pytest.mark.asyncio
    async def test_transient_retry_and_exhaustion(self) -> None:
        """Transient Qdrant failures should be retried up to max_retries."""
        mock_client = MagicMock()
        mock_client.collection_exists = AsyncMock(return_value=True)

        call_count = 0

        async def _flaky_upsert(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("Qdrant connection timed out")
            return MagicMock(status="completed")

        mock_client.upsert = AsyncMock(side_effect=_flaky_upsert)

        store = QdrantVectorStore(
            dimension=2,
            max_retries=3,
            initial_retry_delay_seconds=0.01,
            client=mock_client,
        )

        pts = [VectorPoint(point_id="p1", vector=(1.0, 0.0), payload={})]
        count = await store.upsert_vectors("test_col", pts)
        assert count == 1
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_permanent_error_fails_fast(self) -> None:
        """Non-retryable 400/401 errors must fail immediately without retries."""
        mock_client = MagicMock()
        mock_client.collection_exists = AsyncMock(return_value=True)

        class PermanentAuthError(Exception):
            status_code = 401

        mock_client.upsert = AsyncMock(
            side_effect=PermanentAuthError("Unauthorized API Key")
        )

        store = QdrantVectorStore(
            dimension=2,
            max_retries=3,
            initial_retry_delay_seconds=0.01,
            client=mock_client,
        )

        pts = [VectorPoint(point_id="p1", vector=(1.0, 0.0), payload={})]
        with pytest.raises(PermanentAuthError):
            await store.upsert_vectors("test_col", pts)

        assert mock_client.upsert.call_count == 1

    def test_error_classification(self) -> None:
        """Verify retryable vs non-retryable error classification helper."""
        assert _is_retryable_error(TimeoutError("Deadline exceeded")) is True

        class MockErr(Exception):
            def __init__(self, code: int) -> None:
                self.status_code = code

        assert _is_retryable_error(MockErr(429)) is True
        assert _is_retryable_error(MockErr(503)) is True
        assert _is_retryable_error(MockErr(401)) is False
        assert _is_retryable_error(MockErr(403)) is False


class TestVectorStoreFactory:
    """Test suite for create_vector_store factory constructor."""

    def test_factory_in_memory_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default configuration should instantiate InMemoryVectorStore."""
        monkeypatch.setenv("VECTOR_STORE_PROVIDER", "in_memory")
        settings = AppSettings()
        store = create_vector_store(settings=settings)
        assert isinstance(store, InMemoryVectorStore)

    def test_factory_qdrant_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """qdrant provider configuration should instantiate QdrantVectorStore."""
        monkeypatch.setenv("VECTOR_STORE_PROVIDER", "qdrant")
        monkeypatch.setenv("QDRANT_URL", "http://qdrant-host:6333")
        monkeypatch.setenv("QDRANT_VECTOR_SIZE", "768")
        settings = AppSettings()
        store = create_vector_store(settings=settings)
        assert isinstance(store, QdrantVectorStore)
        assert store.url == "http://qdrant-host:6333"
        assert store.dimension == 768

    def test_factory_injected_instance(self) -> None:
        """Injected test double should be returned directly."""
        mock_store = MagicMock(spec=VectorStoreProtocol)
        settings = AppSettings()
        store = create_vector_store(settings=settings, client=mock_store)
        assert store is mock_store

    def test_factory_unsupported_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unsupported provider setting should raise ValidationError or ValueError."""
        monkeypatch.setenv("VECTOR_STORE_PROVIDER", "pinecone_unsupported")
        with pytest.raises(ValidationError):
            AppSettings()

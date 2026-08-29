"""Unit tests for Phase 6.6 GCSArtifactStorage adapter using deterministic mock clients."""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.storage.gcs import GCSArtifactStorage
from app.storage.models import ArtifactType
from app.storage.protocols import (
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactStorageProtocol,
    ChecksumMismatchError,
)


class FakeGCSBlob:
    """Deterministic fake GCS Blob for testing."""

    def __init__(
        self, name: str, data: bytes = b"", metadata: dict[str, Any] | None = None
    ) -> None:
        self.name = name
        self._data = data
        self.metadata = metadata or {}
        self._exists = bool(data or metadata)

    def exists(self) -> bool:
        return self._exists

    def reload(self) -> None:
        pass

    def upload_from_string(
        self,
        data: bytes,
        content_type: str | None = None,  # noqa: ARG002
    ) -> None:
        self._data = data
        self._exists = True

    def download_as_bytes(self) -> bytes:
        if not self._exists:
            raise Exception("Blob not found")
        return self._data

    def delete(self) -> None:
        self._exists = False
        self._data = b""


class FakeGCSBucket:
    """Deterministic fake GCS Bucket for testing."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.blobs: dict[str, FakeGCSBlob] = {}

    def blob(self, blob_name: str) -> FakeGCSBlob:
        if blob_name not in self.blobs:
            self.blobs[blob_name] = FakeGCSBlob(blob_name)
        return self.blobs[blob_name]


class FakeGCSClient:
    """Deterministic fake GCS Client for testing."""

    def __init__(self) -> None:
        self.buckets: dict[str, FakeGCSBucket] = {}

    def bucket(self, bucket_name: str) -> FakeGCSBucket:
        if bucket_name not in self.buckets:
            self.buckets[bucket_name] = FakeGCSBucket(bucket_name)
        return self.buckets[bucket_name]


class TestGCSArtifactStorage:
    """Unit tests for GCSArtifactStorage."""

    @pytest.mark.asyncio
    async def test_gcs_protocol_conformance(self) -> None:
        client = FakeGCSClient()
        storage = GCSArtifactStorage(bucket_name="test-bucket", client=client)
        assert isinstance(storage, ArtifactStorageProtocol)

    @pytest.mark.asyncio
    async def test_gcs_upload_and_download(self) -> None:
        client = FakeGCSClient()
        storage = GCSArtifactStorage(
            bucket_name="my-bucket",
            client=client,
            prefix="research_artifacts",
        )
        content = "# Autonomous Research Dossier\n\nComprehensive findings."
        meta = await storage.upload(
            run_id="run_gcs_01",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content=content,
            filename="report.md",
            metadata={"source": "agent_worker"},
        )

        assert meta.storage_provider == "gcs"
        assert (
            meta.storage_uri == "gs://my-bucket/research_artifacts/run_gcs_01/report.md"
        )
        assert meta.object_key == "research_artifacts/run_gcs_01/report.md"
        assert meta.size_bytes == len(content.encode("utf-8"))
        assert meta.sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Download with SHA-256 verification
        downloaded = await storage.download(meta, verify_checksum=True)
        assert downloaded.decode("utf-8") == content

    @pytest.mark.asyncio
    async def test_gcs_checksum_mismatch_raises(self) -> None:
        client = FakeGCSClient()
        storage = GCSArtifactStorage(bucket_name="my-bucket", client=client)
        content = "GCS Blob Content"
        meta = await storage.upload(
            run_id="run_gcs_02",
            artifact_type=ArtifactType.DOSSIER_JSON,
            content=content,
        )

        # Manually alter blob data in the fake bucket
        fake_blob = client.buckets["my-bucket"].blobs[meta.object_key]
        fake_blob._data = b"Tampered Content"

        with pytest.raises(ChecksumMismatchError, match="Integrity check failed"):
            await storage.download(meta, verify_checksum=True)

        # Download without verification returns tampered data
        raw = await storage.download(meta, verify_checksum=False)
        assert raw == b"Tampered Content"

    @pytest.mark.asyncio
    async def test_gcs_exists_and_delete(self) -> None:
        client = FakeGCSClient()
        storage = GCSArtifactStorage(bucket_name="my-bucket", client=client)
        meta = await storage.upload(
            run_id="run_gcs_03",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content="Data to delete",
        )

        assert await storage.exists(meta) is True
        assert await storage.delete(meta) is True
        assert await storage.exists(meta) is False
        assert await storage.delete(meta) is False

    @pytest.mark.asyncio
    async def test_gcs_missing_artifact_raises(self) -> None:
        client = FakeGCSClient()
        storage = GCSArtifactStorage(bucket_name="my-bucket", client=client)
        with pytest.raises(ArtifactNotFoundError):
            await storage.download("nonexistent/blob.txt")

    @pytest.mark.asyncio
    async def test_gcs_transient_retry_success(self) -> None:
        """Verify retry mechanism catches transient errors and recovers."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        # Fail twice with transient 503 error, succeed on 3rd attempt
        call_count = 0

        def _flaky_upload(*args: object, **kwargs: object) -> None:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("503 Service Unavailable")

        mock_blob.upload_from_string.side_effect = _flaky_upload

        storage = GCSArtifactStorage(
            bucket_name="retry-bucket",
            client=mock_client,
            max_retries=3,
            initial_backoff=0.01,
        )

        meta = await storage.upload(
            run_id="run_retry",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content="Retried content",
        )
        assert meta.run_id == "run_retry"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_gcs_persistent_error_raises_storage_error(self) -> None:
        """Verify persistent failures raise ArtifactStorageError."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        mock_blob.upload_from_string.side_effect = Exception(
            "403 Forbidden: IAM permission denied"
        )

        storage = GCSArtifactStorage(
            bucket_name="perm-bucket",
            client=mock_client,
            max_retries=2,
            initial_backoff=0.01,
        )

        with pytest.raises(ArtifactStorageError, match="GCS storage operation failed"):
            await storage.upload(
                run_id="run_fail",
                artifact_type=ArtifactType.REPORT_MARKDOWN,
                content="Fail content",
            )

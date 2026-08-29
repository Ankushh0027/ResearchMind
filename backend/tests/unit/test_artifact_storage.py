"""Unit tests for Phase 6.6 Artifact Storage protocol, models, in-memory store, and security validation."""

from __future__ import annotations

import hashlib

import pytest

from app.storage.factory import create_artifact_storage
from app.storage.in_memory import InMemoryArtifactStorage
from app.storage.models import ArtifactMetadata, ArtifactType
from app.storage.protocols import (
    ArtifactNotFoundError,
    ArtifactStorageProtocol,
    ChecksumMismatchError,
    InvalidObjectKeyError,
)
from app.storage.security import validate_object_key


class TestArtifactModels:
    """Validate ArtifactType enums and ArtifactMetadata serialization."""

    def test_artifact_metadata_immutability(self) -> None:
        meta = ArtifactMetadata(
            artifact_id="art_12345",
            run_id="run_test",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            storage_provider="in_memory",
            storage_uri="memory://run_test/report.md",
            object_key="run_test/report.md",
            content_type="text/markdown",
            size_bytes=100,
            sha256="a" * 64,
        )
        assert meta.artifact_id == "art_12345"
        from pydantic import ValidationError

        assert meta.artifact_id == "art_12345"
        assert meta.artifact_type == ArtifactType.REPORT_MARKDOWN
        assert meta.schema_version == 1
        with pytest.raises(ValidationError):  # Frozen instance
            meta.size_bytes = 200


class TestSecurityValidation:
    """Security validation tests for artifact object keys and path traversal."""

    def test_valid_keys_accepted(self) -> None:
        valid_keys = [
            "report.md",
            "dossier.json",
            "subfolder/data.bin",
            "run_123/checkpoints/step_1.json",
            "artifacts_v1.0.txt",
        ]
        for key in valid_keys:
            res = validate_object_key("run_123", key)
            assert res == key

    def test_empty_keys_rejected(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            validate_object_key("run_123", "")
        with pytest.raises(InvalidObjectKeyError):
            validate_object_key("run_123", "   ")
        with pytest.raises(InvalidObjectKeyError):
            validate_object_key("", "report.md")

    def test_directory_traversal_rejected(self) -> None:
        traversal_attempts = [
            "../secret.txt",
            "foo/../../bar",
            "../../etc/passwd",
            "subdir/..",
            "..",
        ]
        for key in traversal_attempts:
            with pytest.raises(InvalidObjectKeyError, match="[Dd]irectory traversal"):
                validate_object_key("run_123", key)

    def test_leading_slash_rejected(self) -> None:
        with pytest.raises(InvalidObjectKeyError, match="leading slash"):
            validate_object_key("run_123", "/absolute/path/report.md")

    def test_backslashes_rejected(self) -> None:
        with pytest.raises(InvalidObjectKeyError, match="backslashes"):
            validate_object_key("run_123", "windows\\path\\report.md")

    def test_null_bytes_and_control_characters_rejected(self) -> None:
        with pytest.raises(InvalidObjectKeyError, match="control characters"):
            validate_object_key("run_123", "report\x00.md")
        with pytest.raises(InvalidObjectKeyError, match="control characters"):
            validate_object_key("run_123", "report\n.md")

    def test_invalid_characters_rejected(self) -> None:
        invalid_keys = [
            "report;rm -rf.md",
            "report$(whoami).json",
            "report`calc`.md",
            "report<script>.md",
        ]
        for key in invalid_keys:
            with pytest.raises(InvalidObjectKeyError, match="Invalid characters"):
                validate_object_key("run_123", key)

    def test_excessive_length_rejected(self) -> None:
        long_key = "a" * 1025
        with pytest.raises(InvalidObjectKeyError, match="exceeds maximum limit"):
            validate_object_key("run_123", long_key)


class TestInMemoryArtifactStorage:
    """Unit tests for the InMemoryArtifactStorage implementation."""

    @pytest.mark.asyncio
    async def test_protocol_conformance(self) -> None:
        storage = InMemoryArtifactStorage()
        assert isinstance(storage, ArtifactStorageProtocol)

    @pytest.mark.asyncio
    async def test_upload_and_download_string(self) -> None:
        storage = InMemoryArtifactStorage()
        content = "# Research Report\n\nKey finding: Success."
        meta = await storage.upload(
            run_id="run_100",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content=content,
            filename="report.md",
        )
        assert meta.run_id == "run_100"
        assert meta.artifact_type == ArtifactType.REPORT_MARKDOWN
        assert meta.size_bytes == len(content.encode("utf-8"))
        assert meta.sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert meta.storage_provider == "in_memory"
        assert meta.content_type == "text/markdown"

        downloaded = await storage.download(meta, verify_checksum=True)
        assert downloaded.decode("utf-8") == content

    @pytest.mark.asyncio
    async def test_upload_and_download_bytes(self) -> None:
        storage = InMemoryArtifactStorage()
        raw_bytes = b"\x00\x01\x02\x03\xff\xfe"
        meta = await storage.upload(
            run_id="run_200",
            artifact_type=ArtifactType.EVIDENCE_BUNDLE,
            content=raw_bytes,
            filename="evidence.bin",
            content_type="application/octet-stream",
        )
        assert meta.size_bytes == len(raw_bytes)
        assert meta.sha256 == hashlib.sha256(raw_bytes).hexdigest()

        downloaded = await storage.download(meta.object_key, verify_checksum=True)
        assert downloaded == raw_bytes

    @pytest.mark.asyncio
    async def test_download_by_artifact_id(self) -> None:
        storage = InMemoryArtifactStorage()
        content = "Sample JSON payload"
        meta = await storage.upload(
            run_id="run_300",
            artifact_type=ArtifactType.DOSSIER_JSON,
            content=content,
        )
        # Download using artifact_id directly
        downloaded = await storage.download(meta.artifact_id, verify_checksum=True)
        assert downloaded.decode("utf-8") == content

    @pytest.mark.asyncio
    async def test_checksum_verification_mismatch(self) -> None:
        storage = InMemoryArtifactStorage()
        content = "Original unaltered content"
        meta = await storage.upload(
            run_id="run_400",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content=content,
        )

        # Create a tampered metadata object with wrong hash
        tampered_meta = ArtifactMetadata(
            artifact_id=meta.artifact_id,
            run_id=meta.run_id,
            artifact_type=meta.artifact_type,
            storage_provider=meta.storage_provider,
            storage_uri=meta.storage_uri,
            object_key=meta.object_key,
            content_type=meta.content_type,
            size_bytes=meta.size_bytes,
            sha256="0" * 64,  # wrong hash
        )

        with pytest.raises(ChecksumMismatchError, match="Integrity check failed"):
            await storage.download(tampered_meta, verify_checksum=True)

        # Downloading without checksum verification succeeds
        data = await storage.download(tampered_meta, verify_checksum=False)
        assert data.decode("utf-8") == content

    @pytest.mark.asyncio
    async def test_exists_and_delete(self) -> None:
        storage = InMemoryArtifactStorage()
        meta = await storage.upload(
            run_id="run_500",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content="To be deleted",
        )
        assert await storage.exists(meta) is True
        assert await storage.exists(meta.artifact_id) is True
        assert await storage.exists("nonexistent_key") is False

        deleted = await storage.delete(meta)
        assert deleted is True
        assert await storage.exists(meta) is False
        assert await storage.delete(meta) is False

    @pytest.mark.asyncio
    async def test_nonexistent_artifact_raises(self) -> None:
        storage = InMemoryArtifactStorage()
        with pytest.raises(ArtifactNotFoundError):
            await storage.download("missing_artifact_123")

    @pytest.mark.asyncio
    async def test_custom_metadata_preserved(self) -> None:
        storage = InMemoryArtifactStorage()
        custom = {"confidence": 0.95, "tags": ["physics", "quantum"]}
        meta = await storage.upload(
            run_id="run_600",
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content="Report with metadata",
            metadata=custom,
        )
        assert meta.metadata["confidence"] == 0.95
        assert meta.metadata["tags"] == ["physics", "quantum"]

    @pytest.mark.asyncio
    async def test_default_filename_heuristics(self) -> None:
        storage = InMemoryArtifactStorage()
        m1 = await storage.upload("r1", ArtifactType.REPORT_MARKDOWN, "md")
        assert m1.object_key.endswith("report.md")

        m2 = await storage.upload("r1", ArtifactType.DOSSIER_JSON, "json")
        assert m2.object_key.endswith("dossier.json")

        m3 = await storage.upload("r1", ArtifactType.CHECKPOINT_SNAPSHOT, "chk")
        assert m3.object_key.endswith("checkpoint.json")


class TestArtifactStorageFactory:
    """Unit tests for the create_artifact_storage factory."""

    def test_create_in_memory_default(self) -> None:
        storage = create_artifact_storage()
        assert isinstance(storage, InMemoryArtifactStorage)

    def test_create_in_memory_explicit(self) -> None:
        storage = create_artifact_storage(provider="in_memory")
        assert isinstance(storage, InMemoryArtifactStorage)

    def test_create_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported artifact storage provider"):
            create_artifact_storage(provider="aws_s3")

    def test_create_gcs_with_mock_client(self) -> None:
        from unittest.mock import MagicMock

        from app.storage.gcs import GCSArtifactStorage

        mock_client = MagicMock()
        storage = create_artifact_storage(
            provider="gcs",
            client=mock_client,
            bucket_name="custom-bucket",
        )
        assert isinstance(storage, GCSArtifactStorage)
        assert storage._bucket_name == "custom-bucket"

"""Thread-safe in-memory implementation of ArtifactStorageProtocol for testing and offline execution."""

import asyncio
import hashlib
import uuid
from typing import Any

from app.storage.models import ArtifactMetadata, ArtifactType
from app.storage.protocols import (
    ArtifactNotFoundError,
    ArtifactStorageProtocol,
    ChecksumMismatchError,
)
from app.storage.security import validate_object_key


class InMemoryArtifactStorage(ArtifactStorageProtocol):
    """Deterministic, thread-safe in-memory artifact blob store."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._metadata: dict[str, ArtifactMetadata] = {}
        self._lock = asyncio.Lock()

    def generate_storage_uri(self, run_id: str, object_key: str) -> str:
        """Generate in-memory storage URI."""
        return f"memory://{run_id}/{object_key}"

    async def upload(
        self,
        run_id: str,
        artifact_type: ArtifactType | str,
        content: bytes | str,
        filename: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactMetadata:
        """Store artifact content in memory and return ArtifactMetadata."""
        payload_bytes = (
            content.encode("utf-8") if isinstance(content, str) else bytes(content)
        )
        sha256_hex = hashlib.sha256(payload_bytes).hexdigest()
        size_bytes = len(payload_bytes)

        # Determine type enum
        typed_type = (
            artifact_type
            if isinstance(artifact_type, ArtifactType)
            else ArtifactType(str(artifact_type))
        )

        # Default filename / content-type heuristics if omitted
        if filename is None:
            if typed_type == ArtifactType.REPORT_MARKDOWN:
                filename = "report.md"
            elif typed_type in (ArtifactType.REPORT_JSON, ArtifactType.DOSSIER_JSON):
                filename = "dossier.json"
            elif typed_type == ArtifactType.CHECKPOINT_SNAPSHOT:
                filename = "checkpoint.json"
            else:
                filename = f"artifact_{uuid.uuid4().hex[:8]}.bin"

        if content_type is None:
            if filename.endswith(".md"):
                content_type = "text/markdown"
            elif filename.endswith(".json"):
                content_type = "application/json"
            elif filename.endswith(".txt"):
                content_type = "text/plain"
            else:
                content_type = "application/octet-stream"

        object_key = f"{run_id}/{filename}"
        validated_key = validate_object_key(run_id, object_key)
        storage_uri = self.generate_storage_uri(run_id, filename)
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"

        artifact_meta = ArtifactMetadata(
            artifact_id=artifact_id,
            run_id=run_id,
            artifact_type=typed_type,
            storage_provider="in_memory",
            storage_uri=storage_uri,
            object_key=validated_key,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256_hex,
            metadata=dict(metadata or {}),
        )

        async with self._lock:
            self._blobs[validated_key] = payload_bytes
            self._metadata[validated_key] = artifact_meta
            # Also index by artifact_id for lookup
            self._metadata[artifact_id] = artifact_meta
            self._blobs[artifact_id] = payload_bytes

        return artifact_meta

    async def download(
        self,
        artifact: ArtifactMetadata | str,
        verify_checksum: bool = True,
    ) -> bytes:
        """Fetch raw artifact content bytes, verifying SHA-256 integrity."""
        expected_sha256: str | None = None
        key: str

        if isinstance(artifact, ArtifactMetadata):
            key = artifact.object_key
            expected_sha256 = artifact.sha256
        else:
            key = str(artifact)

        async with self._lock:
            # Check by object_key first, then artifact_id
            content = self._blobs.get(key)
            if content is None and key in self._metadata:
                meta = self._metadata[key]
                content = self._blobs.get(meta.object_key)
                if expected_sha256 is None:
                    expected_sha256 = meta.sha256

        if content is None:
            raise ArtifactNotFoundError(
                f"Artifact '{key}' not found in in-memory storage"
            )

        if verify_checksum and expected_sha256:
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ChecksumMismatchError(
                    f"Integrity check failed for artifact '{key}': expected {expected_sha256}, got {actual_sha256}"
                )

        return content

    async def exists(self, artifact: ArtifactMetadata | str) -> bool:
        """Check whether an artifact exists in memory."""
        key = (
            artifact.object_key
            if isinstance(artifact, ArtifactMetadata)
            else str(artifact)
        )
        async with self._lock:
            return key in self._blobs or key in self._metadata

    async def delete(self, artifact: ArtifactMetadata | str) -> bool:
        """Remove an artifact from in-memory storage."""
        key = (
            artifact.object_key
            if isinstance(artifact, ArtifactMetadata)
            else str(artifact)
        )
        async with self._lock:
            removed = False
            if key in self._blobs:
                del self._blobs[key]
                removed = True
            if key in self._metadata:
                meta = self._metadata[key]
                if meta.object_key in self._blobs:
                    del self._blobs[meta.object_key]
                del self._metadata[key]
                removed = True
            return removed


__all__ = ["InMemoryArtifactStorage"]

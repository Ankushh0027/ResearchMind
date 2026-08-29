"""Storage repository protocols and domain exceptions for Phase 6.6."""

from typing import Any, Protocol, runtime_checkable

from app.storage.models import ArtifactMetadata, ArtifactType


class ArtifactStorageError(Exception):
    """Base exception for artifact storage and retrieval operations."""


class ArtifactNotFoundError(ArtifactStorageError):
    """Raised when an artifact cannot be located by key, reference, or URI."""


class ChecksumMismatchError(ArtifactStorageError):
    """Raised when downloaded artifact content does not match expected SHA-256 digest."""


class InvalidObjectKeyError(ArtifactStorageError):
    """Raised when an object key violates naming or path traversal security constraints."""


@runtime_checkable
class ArtifactStorageProtocol(Protocol):
    """Provider-agnostic interface for durable research artifact blob storage."""

    async def upload(
        self,
        run_id: str,
        artifact_type: ArtifactType | str,
        content: bytes | str,
        filename: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactMetadata:
        """Store artifact content and return immutable ArtifactMetadata reference."""
        ...

    async def download(
        self,
        artifact: ArtifactMetadata | str,
        verify_checksum: bool = True,
    ) -> bytes:
        """Fetch raw artifact content bytes, optionally verifying SHA-256 integrity."""
        ...

    async def exists(self, artifact: ArtifactMetadata | str) -> bool:
        """Check whether an artifact exists in the storage provider."""
        ...

    async def delete(self, artifact: ArtifactMetadata | str) -> bool:
        """Delete an artifact from the storage provider. Returns True if removed."""
        ...

    def generate_storage_uri(self, run_id: str, object_key: str) -> str:
        """Generate a canonical storage URI for a given run and object key."""
        ...


__all__ = [
    "ArtifactNotFoundError",
    "ArtifactStorageError",
    "ArtifactStorageProtocol",
    "ChecksumMismatchError",
    "InvalidObjectKeyError",
]

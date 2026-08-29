"""Google Cloud Storage (GCS) implementation of ArtifactStorageProtocol."""

import asyncio
import hashlib
import logging
import uuid
from typing import Any

from app.storage.models import ArtifactMetadata, ArtifactType
from app.storage.protocols import (
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactStorageProtocol,
    ChecksumMismatchError,
)
from app.storage.security import validate_object_key

logger = logging.getLogger("researchmind.storage.gcs")


def _create_gcs_client(project_id: str | None) -> Any:
    """Instantiate a Google Cloud Storage client with clear import error handling."""
    try:
        import google.cloud.storage as storage

        return storage.Client(project=project_id)
    except (ImportError, AttributeError) as e:
        raise RuntimeError(
            "google-cloud-storage is required for GCS artifact persistence. "
            "Install with: pip install google-cloud-storage"
        ) from e


class GCSArtifactStorage(ArtifactStorageProtocol):
    """Production-grade Google Cloud Storage blob repository for ResearchMind artifacts."""

    def __init__(
        self,
        bucket_name: str,
        client: Any = None,
        project_id: str | None = None,
        prefix: str = "artifacts",
        max_retries: int = 3,
        initial_backoff: float = 0.5,
    ) -> None:
        self._bucket_name = bucket_name
        self._client = client
        self._project_id = project_id
        self._prefix = prefix.strip("/ ") if prefix else ""
        self._max_retries = max_retries
        self._initial_backoff = initial_backoff
        self._bucket_obj: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _create_gcs_client(project_id=self._project_id)
        return self._client

    def _get_bucket(self) -> Any:
        if self._bucket_obj is None:
            client = self._get_client()
            self._bucket_obj = client.bucket(self._bucket_name)
        return self._bucket_obj

    def generate_storage_uri(
        self,
        run_id: str,  # noqa: ARG002 — required by ArtifactStorageProtocol signature
        object_key: str,
    ) -> str:
        """Generate canonical GCS storage URI."""
        full_key = f"{self._prefix}/{object_key}" if self._prefix else object_key
        return f"gs://{self._bucket_name}/{full_key}"

    def _build_full_key(self, object_key: str) -> str:
        """Combine prefix and object key."""
        if self._prefix and not object_key.startswith(f"{self._prefix}/"):
            return f"{self._prefix}/{object_key}"
        return object_key

    async def _execute_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a blocking GCS operation in an executor with exponential backoff for transient errors."""
        backoff = self._initial_backoff
        last_exception: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
            except Exception as e:
                last_exception = e
                # Check for transient error or 429/500/502/503/504
                error_str = str(e).lower()
                is_transient = any(
                    code in error_str
                    for code in (
                        "500",
                        "502",
                        "503",
                        "504",
                        "429",
                        "connection",
                        "timeout",
                        "reset by peer",
                    )
                )
                if not is_transient or attempt == self._max_retries:
                    break
                logger.warning(
                    "Transient GCS operation error (attempt %d/%d): %s. Retrying in %.2fs...",
                    attempt,
                    self._max_retries,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff *= 2

        raise ArtifactStorageError(
            f"GCS storage operation failed: {last_exception}"
        ) from last_exception

    async def upload(
        self,
        run_id: str,
        artifact_type: ArtifactType | str,
        content: bytes | str,
        filename: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactMetadata:
        """Upload an artifact to Google Cloud Storage with integrity digest."""
        payload_bytes = (
            content.encode("utf-8") if isinstance(content, str) else bytes(content)
        )
        sha256_hex = hashlib.sha256(payload_bytes).hexdigest()
        size_bytes = len(payload_bytes)

        typed_type = (
            artifact_type
            if isinstance(artifact_type, ArtifactType)
            else ArtifactType(str(artifact_type))
        )

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

        scoped_key = f"{run_id}/{filename}"
        validated_scoped_key = validate_object_key(run_id, scoped_key)
        full_object_key = self._build_full_key(validated_scoped_key)
        storage_uri = f"gs://{self._bucket_name}/{full_object_key}"
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"

        gcs_custom_metadata = {
            "sha256": sha256_hex,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "artifact_type": typed_type.value,
            "schema_version": "1",
        }
        if metadata:
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    gcs_custom_metadata[f"meta_{k}"] = str(v)

        def _upload_sync() -> None:
            bucket = self._get_bucket()
            blob = bucket.blob(full_object_key)
            blob.metadata = gcs_custom_metadata
            blob.upload_from_string(payload_bytes, content_type=content_type)

        await self._execute_with_retry(_upload_sync)

        return ArtifactMetadata(
            artifact_id=artifact_id,
            run_id=run_id,
            artifact_type=typed_type,
            storage_provider="gcs",
            storage_uri=storage_uri,
            object_key=full_object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256_hex,
            metadata=dict(metadata or {}),
        )

    async def download(
        self,
        artifact: ArtifactMetadata | str,
        verify_checksum: bool = True,
    ) -> bytes:
        """Download artifact blob from GCS, verifying SHA-256 integrity."""
        expected_sha256: str | None = None
        full_key: str

        if isinstance(artifact, ArtifactMetadata):
            full_key = artifact.object_key
            expected_sha256 = artifact.sha256
        else:
            full_key = self._build_full_key(str(artifact))

        def _download_sync() -> tuple[bytes, dict[str, Any] | None]:
            bucket = self._get_bucket()
            blob = bucket.blob(full_key)
            if not blob.exists():
                return b"", None
            blob.reload()
            data = blob.download_as_bytes()
            return data, blob.metadata

        try:
            content, blob_metadata = await self._execute_with_retry(_download_sync)
        except ArtifactStorageError:
            raise
        except Exception as e:
            raise ArtifactStorageError(
                f"Failed to download blob '{full_key}': {e}"
            ) from e

        if blob_metadata is None:
            raise ArtifactNotFoundError(
                f"Artifact '{full_key}' does not exist in bucket '{self._bucket_name}'"
            )

        if expected_sha256 is None and blob_metadata and "sha256" in blob_metadata:
            expected_sha256 = blob_metadata["sha256"]

        if verify_checksum and expected_sha256:
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ChecksumMismatchError(
                    f"Integrity check failed for GCS blob '{full_key}': expected {expected_sha256}, got {actual_sha256}"
                )

        return bytes(content)

    async def exists(self, artifact: ArtifactMetadata | str) -> bool:
        """Check if an artifact exists in GCS."""
        full_key = (
            artifact.object_key
            if isinstance(artifact, ArtifactMetadata)
            else self._build_full_key(str(artifact))
        )

        def _exists_sync() -> bool:
            bucket = self._get_bucket()
            blob = bucket.blob(full_key)
            return bool(blob.exists())

        return bool(await self._execute_with_retry(_exists_sync))

    async def delete(self, artifact: ArtifactMetadata | str) -> bool:
        """Delete an artifact from GCS."""
        full_key = (
            artifact.object_key
            if isinstance(artifact, ArtifactMetadata)
            else self._build_full_key(str(artifact))
        )

        def _delete_sync() -> bool:
            bucket = self._get_bucket()
            blob = bucket.blob(full_key)
            if not blob.exists():
                return False
            blob.delete()
            return True

        return bool(await self._execute_with_retry(_delete_sync))


__all__ = ["GCSArtifactStorage"]

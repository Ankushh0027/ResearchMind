"""Factory module for creating configured ArtifactStorageProtocol instances."""

from typing import Any

from app.config.settings import AppSettings, get_settings
from app.storage.gcs import GCSArtifactStorage
from app.storage.in_memory import InMemoryArtifactStorage
from app.storage.protocols import ArtifactStorageProtocol


def create_artifact_storage(
    settings: AppSettings | None = None,
    provider: str | None = None,
    client: Any = None,
    bucket_name: str | None = None,
) -> ArtifactStorageProtocol:
    """Construct an ArtifactStorageProtocol provider based on configuration or explicit overrides.

    Supported providers:
    - 'in_memory': Deterministic, thread-safe in-memory store for tests and offline usage.
    - 'gcs': Production Google Cloud Storage blob repository.

    Args:
        settings: Application settings singleton or custom instance.
        provider: Explicit provider override ('in_memory' or 'gcs').
        client: Optional injected Google Cloud Storage client for testing.
        bucket_name: Optional bucket name override.

    Returns:
        Configured ArtifactStorageProtocol instance.

    Raises:
        ValueError: If provider is unrecognized.
    """
    cfg = settings or get_settings()
    active_provider = (provider or cfg.artifact_storage_provider).lower().strip()

    if active_provider in ("in_memory", "memory"):
        return InMemoryArtifactStorage()

    if active_provider in ("gcs", "google_cloud_storage"):
        target_bucket = bucket_name or cfg.gcs_bucket
        target_project = cfg.gcs_project or cfg.gcp_project_id
        return GCSArtifactStorage(
            bucket_name=target_bucket,
            client=client,
            project_id=target_project,
            prefix=cfg.gcs_prefix,
        )

    raise ValueError(
        f"Unsupported artifact storage provider '{active_provider}'. "
        "Must be 'in_memory' or 'gcs'."
    )


__all__ = ["create_artifact_storage"]

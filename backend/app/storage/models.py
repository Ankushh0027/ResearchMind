"""Domain models, enums, and schemas for durable artifact storage."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ArtifactType(StrEnum):
    """Classification of durable research artifacts."""

    REPORT_MARKDOWN = "report_markdown"
    REPORT_JSON = "report_json"
    DOSSIER_JSON = "dossier_json"
    CHECKPOINT_SNAPSHOT = "checkpoint_snapshot"
    EVIDENCE_BUNDLE = "evidence_bundle"
    OTHER = "other"


class ArtifactMetadata(BaseModel):
    """Immutable persistent metadata and reference for a durable research artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str = Field(
        ..., min_length=1, description="Unique artifact identifier"
    )
    run_id: str = Field(
        ..., min_length=1, description="Associated research run identifier"
    )
    artifact_type: ArtifactType = Field(
        ..., description="Categorical type of the artifact"
    )
    storage_provider: str = Field(
        ..., min_length=1, description="Storage backend ('in_memory', 'gcs', etc.)"
    )
    storage_uri: str = Field(
        ..., min_length=1, description="Canonical storage URI (e.g. gs://bucket/key)"
    )
    object_key: str = Field(
        ..., min_length=1, description="Relative or scoped object key"
    )
    content_type: str = Field(
        default="application/octet-stream",
        description="MIME content type of the stored blob",
    )
    size_bytes: int = Field(..., ge=0, description="Size of the payload in bytes")
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Hexadecimal SHA-256 integrity digest",
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Upload and creation timestamp"
    )
    schema_version: int = Field(default=1, ge=1, description="Metadata schema version")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Custom domain and execution metadata"
    )


__all__ = [
    "ArtifactMetadata",
    "ArtifactType",
]

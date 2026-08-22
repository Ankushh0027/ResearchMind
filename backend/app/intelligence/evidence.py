"""Evidence domain models, cryptographic provenance, and SHA-256 hashing."""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.enums import SourceTrustLevel

HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DISALLOWED_URI_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def compute_sha256_hash(content: str | bytes) -> str:
    """Compute deterministic, lowercase hexadecimal SHA-256 hash of canonical UTF-8 content."""
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    elif isinstance(content, (bytes, bytearray)):
        content_bytes = bytes(content)
    else:
        raise TypeError(
            f"Expected str or bytes for content hashing, got {type(content).__name__}"
        )
    return hashlib.sha256(content_bytes).hexdigest()


def generate_evidence_id(prefix: str = "ev") -> str:
    """Generate a unique evidence record identifier independent from content hashes."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def generate_source_id(prefix: str = "src") -> str:
    """Generate a unique source provenance identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class SourceProvenance(BaseModel):
    """Immutable provenance tracking the origin, publisher, and cryptographic hash of external content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(
        default_factory=generate_source_id,
        min_length=1,
        description="Unique provenance identifier",
    )
    source_type: str = Field(
        default="web",
        min_length=1,
        description="Source classification (e.g. web, academic_paper, documentation)",
    )
    source_url: str | None = Field(
        default=None,
        description="Canonical source URL or URI",
    )
    doi: str | None = Field(
        default=None,
        description="Digital Object Identifier for academic publications",
    )
    publisher: str | None = Field(
        default=None,
        description="Publisher, issuing journal, or organization name",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Document or article title",
    )
    authors: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Identified authors or contributors",
    )
    domain: str = Field(
        default="",
        description="Source host domain",
    )
    trust_level: SourceTrustLevel = Field(
        default=SourceTrustLevel.GENERAL_WEB,
        description="Assessed trust tier of the source",
    )
    retrieval_timestamp: datetime = Field(
        default_factory=_utc_now,
        description="Timestamp of document retrieval",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional harvested metadata",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Cryptographic SHA-256 hash of raw source content",
    )

    @field_validator("title")
    @classmethod
    def validate_title_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be empty or whitespace only")
        return v.strip()

    @field_validator("source_type")
    @classmethod
    def validate_source_type_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Source type must not be empty or whitespace only")
        return v.strip()

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash_hex(cls, v: str) -> str:
        v_lower = v.lower()
        if not HEX_64_PATTERN.match(v_lower):
            raise ValueError(
                "Content hash must be a 64-character lowercase hexadecimal SHA-256 string"
            )
        return v_lower

    @field_validator("source_url")
    @classmethod
    def validate_source_url_scheme(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("Source URL must not be empty if provided")
        lower_url = v_clean.lower()
        if any(lower_url.startswith(scheme) for scheme in DISALLOWED_URI_SCHEMES):
            raise ValueError(f"Disallowed URI scheme in source URL: '{v_clean}'")
        return v_clean

    @classmethod
    def from_content(
        cls,
        raw_content: str | bytes,
        title: str,
        source_url: str | None = None,
        doi: str | None = None,
        source_type: str = "web",
        publisher: str | None = None,
        authors: tuple[str, ...] = (),
        domain: str = "",
        trust_level: SourceTrustLevel = SourceTrustLevel.GENERAL_WEB,
        metadata: dict[str, Any] | None = None,
        source_id: str | None = None,
    ) -> "SourceProvenance":
        """Convenience factory creating a SourceProvenance from raw content by computing its SHA-256 hash."""
        computed_hash = compute_sha256_hash(raw_content)
        return cls(
            source_id=source_id or generate_source_id(),
            source_type=source_type,
            source_url=source_url,
            doi=doi,
            publisher=publisher,
            title=title,
            authors=authors,
            domain=domain,
            trust_level=trust_level,
            metadata=metadata or {},
            content_hash=computed_hash,
        )


class EvidenceRecord(BaseModel):
    """Immutable factual evidence item with cryptographic provenance and run isolation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(
        default_factory=generate_evidence_id,
        min_length=1,
        description="Unique evidence record identifier (distinct from content hash)",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="Research run identifier enforcing multi-tenant isolation",
    )
    provenance: SourceProvenance = Field(
        ...,
        description="Cryptographic provenance information of the source document",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Cryptographic SHA-256 hash of normalized evidence content",
    )
    normalized_content: str = Field(
        ...,
        min_length=1,
        description="Normalized factual text content",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual metadata associated with this evidence",
    )
    is_untrusted: bool = Field(
        default=False,
        description="Flag indicating whether the source text requires sanitization or boundary encapsulation",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Flag indicating whether hostile injection indicators were detected",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Creation timestamp",
    )

    @field_validator("run_id")
    @classmethod
    def validate_run_id_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Run ID must not be empty or whitespace only")
        return v.strip()

    @field_validator("normalized_content")
    @classmethod
    def validate_normalized_content_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Normalized content must not be empty or whitespace only")
        return v

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash_hex(cls, v: str) -> str:
        v_lower = v.lower()
        if not HEX_64_PATTERN.match(v_lower):
            raise ValueError(
                "Content hash must be a 64-character lowercase hexadecimal SHA-256 string"
            )
        return v_lower

    @model_validator(mode="after")
    def validate_id_and_hash_integrity(self) -> "EvidenceRecord":
        if self.evidence_id == self.content_hash:
            raise ValueError(
                f"evidence_id '{self.evidence_id}' must not equal content_hash. "
                "Evidence IDs represent identity; hashes represent content equivalence."
            )
        if self.content_hash != self.provenance.content_hash:
            raise ValueError(
                f"EvidenceRecord content_hash '{self.content_hash}' does not match "
                f"SourceProvenance content_hash '{self.provenance.content_hash}'"
            )
        return self

    @classmethod
    def create(
        cls,
        run_id: str,
        normalized_content: str,
        provenance: SourceProvenance,
        evidence_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        is_untrusted: bool = False,
        is_quarantined: bool = False,
    ) -> "EvidenceRecord":
        """Convenience factory creating a validated EvidenceRecord with automated ID and content hash verification."""
        content_hash = compute_sha256_hash(normalized_content)
        # If provenance has different hash, align provenance or verify
        if provenance.content_hash != content_hash:
            provenance = provenance.model_copy(update={"content_hash": content_hash})
        return cls(
            evidence_id=evidence_id or generate_evidence_id(),
            run_id=run_id,
            provenance=provenance,
            content_hash=content_hash,
            normalized_content=normalized_content,
            metadata=metadata or {},
            is_untrusted=is_untrusted,
            is_quarantined=is_quarantined,
        )

"""Evidence ingestion pipeline, raw document schemas, and cryptographic deduplication.

Ingests raw external documents (web pages, academic papers, documentation), computes deterministic
SHA-256 content hashes, executes content boundary sanitization, detects prompt injections, deduplicates
per run_id, and constructs immutable EvidenceRecord instances for downstream memory indexing.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.enums import SourceTrustLevel
from app.common.errors import (
    EvidenceIngestionError,
    EvidenceValidationError,
    InvalidSourceURLError,
    OversizedContentError,
)
from app.intelligence.evidence import (
    DISALLOWED_URI_SCHEMES,
    EvidenceRecord,
    SourceProvenance,
    compute_sha256_hash,
)
from app.intelligence.protocols import VectorMemoryProtocol
from app.intelligence.sanitization import (
    MAX_RAW_TEXT_BYTES,
    ContentBoundarySanitizer,
    UntrustedContentEnvelope,
)


class RawDocument(BaseModel):
    """Input schema representing harvested raw discovery content before sanitization and indexing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_url: str = Field(
        ...,
        min_length=1,
        description="Canonical source URL or DOI URI",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Document or article headline",
    )
    raw_text: str = Field(
        ...,
        min_length=1,
        description="Raw harvested text content",
    )
    domain: str = Field(
        default="",
        description="Root domain or publishing host",
    )
    authors: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Author or contributor names",
    )
    doi: str | None = Field(
        default=None,
        description="Digital Object Identifier if academic source",
    )
    source_type: str = Field(
        default="web",
        description="Classification (e.g. web, academic_paper, documentation)",
    )
    publisher: str | None = Field(
        default=None,
        description="Issuing publisher or journal organization",
    )
    publication_date: str | None = Field(
        default=None,
        description="ISO publication date",
    )
    trust_level: SourceTrustLevel = Field(
        default=SourceTrustLevel.GENERAL_WEB,
        description="Source trust tier",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary harvested metadata",
    )

    @field_validator("source_url")
    @classmethod
    def validate_source_url_scheme(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_url must not be empty or whitespace only")
        v_clean = v.strip()
        lower_url = v_clean.lower()
        if any(lower_url.startswith(scheme) for scheme in DISALLOWED_URI_SCHEMES):
            raise ValueError(f"Disallowed URI scheme in source_url: '{v_clean}'")
        return v_clean

    @field_validator("title", "raw_text")
    @classmethod
    def validate_non_empty_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty or whitespace only")
        return v


class IngestionResult(BaseModel):
    """Result envelope returned by the EvidenceIngestionPipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_record: EvidenceRecord = Field(
        ...,
        description="Assembled immutable evidence record",
    )
    envelope: UntrustedContentEnvelope = Field(
        ...,
        description="Security sanitization envelope",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Canonical SHA-256 content hash",
    )
    is_duplicate: bool = Field(
        default=False,
        description="Whether payload was already ingested in this run",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Whether hostile injection triggers were detected",
    )


class EvidenceIngestionPipeline:
    """Security-preserving, deduplicating evidence ingestion pipeline."""

    def __init__(
        self,
        vector_memory: VectorMemoryProtocol | None = None,
        max_raw_text_bytes: int = MAX_RAW_TEXT_BYTES,
    ) -> None:
        if (
            not isinstance(max_raw_text_bytes, int)
            or isinstance(max_raw_text_bytes, bool)
            or max_raw_text_bytes <= 0
        ):
            raise EvidenceValidationError(
                f"max_raw_text_bytes must be a positive integer, got {max_raw_text_bytes}"
            )
        self.vector_memory = vector_memory
        self.max_raw_text_bytes = max_raw_text_bytes
        # Ingestion deduplication registry: (run_id, content_hash) -> EvidenceRecord
        self._seen_hashes: dict[tuple[str, str], EvidenceRecord] = {}

    def get_ingested_record(
        self, run_id: str, content_hash: str
    ) -> EvidenceRecord | None:
        """Look up an already ingested record by (run_id, content_hash)."""
        return self._seen_hashes.get((run_id.strip(), content_hash.lower()))

    def is_already_ingested(self, run_id: str, content_hash: str) -> bool:
        """Check if content has already been ingested for this run_id."""
        return (run_id.strip(), content_hash.lower()) in self._seen_hashes

    def count(self, run_id: str | None = None) -> int:
        """Return count of ingested records, optionally filtered by run_id."""
        if run_id is None:
            return len(self._seen_hashes)
        clean_run = run_id.strip()
        return sum(1 for (r_id, _) in self._seen_hashes if r_id == clean_run)

    async def ingest_document(
        self,
        document: RawDocument,
        run_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Ingest a RawDocument through validation, hashing, sanitization, dedup, and record assembly."""
        if document is None:
            raise TypeError("document cannot be None")
        if not isinstance(document, RawDocument):
            raise TypeError(f"Expected RawDocument, got {type(document).__name__}")

        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty or whitespace only")
        clean_run_id = run_id.strip()

        # 1. Input & URL Scheme Validation
        raw_bytes = document.raw_text.encode("utf-8")
        if len(raw_bytes) > self.max_raw_text_bytes:
            raise OversizedContentError(
                byte_count=len(raw_bytes),
                max_bytes=self.max_raw_text_bytes,
            )

        if not document.raw_text.strip():
            raise EvidenceIngestionError(
                "raw_text must not be empty or whitespace only",
                code="EMPTY_CONTENT",
            )

        lower_url = document.source_url.lower()
        if any(lower_url.startswith(scheme) for scheme in DISALLOWED_URI_SCHEMES):
            raise InvalidSourceURLError(
                source_url=document.source_url,
                reason="Disallowed URI scheme (javascript/data/vbscript/file)",
            )

        # 2. Canonical Content Hashing
        content_hash = compute_sha256_hash(document.raw_text)
        dedup_key = (clean_run_id, content_hash)

        # 3. Deduplication Check
        if dedup_key in self._seen_hashes:
            existing_record = self._seen_hashes[dedup_key]
            envelope = ContentBoundarySanitizer.wrap_evidence(existing_record)
            return IngestionResult(
                evidence_record=existing_record,
                envelope=envelope,
                content_hash=content_hash,
                is_duplicate=True,
                is_quarantined=existing_record.is_quarantined,
            )

        # 4. Untrusted Content Boundary & Sanitization
        envelope = ContentBoundarySanitizer.sanitize_raw(
            raw_text=document.raw_text,
            run_id=clean_run_id,
            metadata=document.metadata,
        )

        # 5. Provenance & Evidence Record Construction
        # Provenance retains original raw content hash for cryptographic verification
        provenance = SourceProvenance(
            source_type=document.source_type,
            source_url=document.source_url,
            doi=document.doi,
            publisher=document.publisher,
            title=document.title,
            authors=document.authors,
            domain=document.domain,
            trust_level=document.trust_level,
            metadata=document.metadata,
            content_hash=content_hash,
        )

        merged_metadata = dict(document.metadata)
        if metadata:
            merged_metadata.update(metadata)

        evidence_record = EvidenceRecord.create(
            run_id=clean_run_id,
            normalized_content=envelope.sanitized_content,
            provenance=provenance,
            metadata=merged_metadata,
            is_untrusted=True,
            is_quarantined=envelope.is_quarantined,
        )

        # Register in run-scoped deduplication registry
        self._seen_hashes[dedup_key] = evidence_record

        # 6. Optional Vector Memory Upsert
        if self.vector_memory is not None:
            await self.vector_memory.upsert_evidence([evidence_record])

        return IngestionResult(
            evidence_record=evidence_record,
            envelope=envelope,
            content_hash=content_hash,
            is_duplicate=False,
            is_quarantined=envelope.is_quarantined,
        )

    async def ingest_batch(
        self,
        documents: list[RawDocument],
        run_id: str,
    ) -> list[IngestionResult]:
        """Ingest a list of RawDocuments for a given run_id in sequence."""
        if documents is None or not isinstance(documents, list):
            raise TypeError("documents must be a list of RawDocument instances")

        results: list[IngestionResult] = []
        for doc in documents:
            res = await self.ingest_document(document=doc, run_id=run_id)
            results.append(res)
        return results


__all__ = [
    "EvidenceIngestionPipeline",
    "IngestionResult",
    "RawDocument",
]

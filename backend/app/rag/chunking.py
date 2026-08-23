"""Deterministic text chunking for evidence ingestion and RAG memory.

Provides deterministic sliding-window chunking of sanitized evidence documents into
immutable TextChunk models with strict offset tracking, stable chunk IDs, and
multi-tenant run isolation.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.errors import EvidenceValidationError
from app.intelligence.evidence import EvidenceRecord

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_MAX_CHUNKS = 200


class TextChunk(BaseModel):
    """Discrete, immutable sub-segment of an evidence document with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(
        ...,
        min_length=1,
        description="Deterministic unique chunk identifier: chk_{evidence_id}_{chunk_index}",
    )
    evidence_id: str = Field(
        ...,
        min_length=1,
        description="Parent EvidenceRecord identifier",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="Associated research run identifier for strict isolation",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Chunk text content",
    )
    chunk_index: int = Field(
        ...,
        ge=0,
        description="Zero-based sequence index of the chunk",
    )
    total_chunks: int = Field(
        default=1,
        ge=1,
        description="Total number of chunks produced from parent evidence",
    )
    start_offset: int = Field(
        ...,
        ge=0,
        description="Starting character offset in parent evidence text",
    )
    end_offset: int = Field(
        ...,
        ge=0,
        description="Ending character offset in parent evidence text",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Inherited and chunk-level metadata",
    )

    @property
    def start_char_idx(self) -> int:
        """Alias for start_offset."""
        return self.start_offset

    @property
    def end_char_idx(self) -> int:
        """Alias for end_offset."""
        return self.end_offset

    @field_validator("chunk_id", "evidence_id", "run_id")
    @classmethod
    def validate_non_empty_identifiers(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Identifier fields must not be empty or whitespace only")
        return v.strip()

    @field_validator("text")
    @classmethod
    def validate_non_empty_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Chunk text must not be empty or whitespace only")
        return v

    @model_validator(mode="after")
    def validate_offsets_and_span(self) -> "TextChunk":
        if self.end_offset < self.start_offset:
            raise ValueError(
                f"end_offset ({self.end_offset}) must be >= start_offset ({self.start_offset})"
            )
        expected_len = self.end_offset - self.start_offset
        if len(self.text) != expected_len:
            raise ValueError(
                f"Text length ({len(self.text)}) does not match offset span ({expected_len})"
            )
        return self


class DeterministicTextChunker:
    """Deterministic character-based sliding-window chunker for evidence text."""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        max_chunks_per_document: int = DEFAULT_MAX_CHUNKS,
    ) -> None:
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
            raise TypeError(
                f"chunk_size must be an integer, got {type(chunk_size).__name__}"
            )
        if chunk_size <= 0:
            raise EvidenceValidationError(
                f"chunk_size must be a positive integer, got {chunk_size}",
                {"chunk_size": chunk_size},
            )

        if not isinstance(chunk_overlap, int) or isinstance(chunk_overlap, bool):
            raise TypeError(
                f"chunk_overlap must be an integer, got {type(chunk_overlap).__name__}"
            )
        if chunk_overlap < 0:
            raise EvidenceValidationError(
                f"chunk_overlap must be non-negative, got {chunk_overlap}",
                {"chunk_overlap": chunk_overlap},
            )
        if chunk_overlap >= chunk_size:
            raise EvidenceValidationError(
                f"chunk_overlap ({chunk_overlap}) must be strictly less than chunk_size ({chunk_size})",
                {"chunk_overlap": chunk_overlap, "chunk_size": chunk_size},
            )

        if (
            not isinstance(max_chunks_per_document, int)
            or isinstance(max_chunks_per_document, bool)
            or max_chunks_per_document <= 0
        ):
            raise EvidenceValidationError(
                f"max_chunks_per_document must be a positive integer, got {max_chunks_per_document}",
                {"max_chunks_per_document": max_chunks_per_document},
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_chunks_per_document = max_chunks_per_document
        self._step = chunk_size - chunk_overlap

    def chunk_evidence(self, evidence: EvidenceRecord) -> list[TextChunk]:
        """Chunk a validated EvidenceRecord into overlapping TextChunk items."""
        if evidence is None:
            raise TypeError("evidence cannot be None")
        if not isinstance(evidence, EvidenceRecord):
            raise TypeError(f"Expected EvidenceRecord, got {type(evidence).__name__}")

        return self.chunk_text(
            text=evidence.normalized_content,
            evidence_id=evidence.evidence_id,
            run_id=evidence.run_id,
            metadata=evidence.metadata,
        )

    def chunk_text(
        self,
        text: str,
        evidence_id: str,
        run_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """Chunk raw or normalized text into overlapping TextChunk items with given provenance."""
        if text is None:
            raise TypeError("text cannot be None")
        if not isinstance(text, str):
            raise TypeError(f"Expected str for text, got {type(text).__name__}")
        if not text.strip():
            raise EvidenceValidationError(
                "Evidence text must not be empty or whitespace only"
            )

        if not evidence_id or not evidence_id.strip():
            raise EvidenceValidationError(
                "evidence_id must not be empty or whitespace only"
            )
        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty or whitespace only")

        clean_evidence_id = evidence_id.strip()
        clean_run_id = run_id.strip()

        text_len = len(text)
        spans: list[tuple[int, int]] = []

        if text_len <= self.chunk_size:
            spans.append((0, text_len))
        else:
            start = 0
            while start < text_len:
                end = min(start + self.chunk_size, text_len)
                spans.append((start, end))
                if end == text_len:
                    break
                start += self._step
                if len(spans) > self.max_chunks_per_document:
                    raise EvidenceValidationError(
                        f"Document produced {len(spans)} chunks, exceeding max_chunks_per_document ({self.max_chunks_per_document})",
                        {
                            "chunk_count": len(spans),
                            "max_chunks": self.max_chunks_per_document,
                        },
                    )

        total_chunks = len(spans)
        chunks: list[TextChunk] = []

        for idx, (start_offset, end_offset) in enumerate(spans):
            chunk_text_slice = text[start_offset:end_offset]
            chunk_id = f"chk_{clean_evidence_id}_{idx}"

            # Inherit metadata safely without letting user metadata overwrite provenance attributes
            chunk_meta = dict(metadata) if metadata else {}
            chunk_meta["evidence_id"] = clean_evidence_id
            chunk_meta["run_id"] = clean_run_id
            chunk_meta["chunk_index"] = idx
            chunk_meta["total_chunks"] = total_chunks
            chunk_meta["start_offset"] = start_offset
            chunk_meta["end_offset"] = end_offset

            chunk = TextChunk(
                chunk_id=chunk_id,
                evidence_id=clean_evidence_id,
                run_id=clean_run_id,
                text=chunk_text_slice,
                chunk_index=idx,
                total_chunks=total_chunks,
                start_offset=start_offset,
                end_offset=end_offset,
                metadata=chunk_meta,
            )
            chunks.append(chunk)

        return chunks


# Canonical alias
TextChunker = DeterministicTextChunker

__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MAX_CHUNKS",
    "DeterministicTextChunker",
    "TextChunk",
    "TextChunker",
]

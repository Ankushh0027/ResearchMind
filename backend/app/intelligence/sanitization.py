"""Content Boundary Sanitization and Untrusted Evidence Security.

Treats all external evidence as untrusted data, neutralizes known prompt-injection
control patterns, handles fake system/developer messages, and encapsulates evidence
in immutable UntrustedContentEnvelope representations without interpreting instructions.
"""

import html
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import SourceTrustLevel
from app.common.errors import EvidenceValidationError
from app.intelligence.evidence import (
    EvidenceRecord,
    SourceProvenance,
    compute_sha256_hash,
)

MAX_RAW_TEXT_BYTES = 1_000_000  # 1 MB maximum boundary per evidence document

# Known prompt-control tags and instruction hijack phrases (case-insensitive)
CONTROL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*user\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*assistant\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*developer\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*instruction\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*evidence\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*evidence_snippet\s*>", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(
        r"disregard\s+(all\s+)?(prior|previous)\s+(prompts|instructions)", re.IGNORECASE
    ),
    re.compile(r"system\s+message\s*:", re.IGNORECASE),
    re.compile(r"developer\s+message\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now(\s+in)?\s+developer\s+mode", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+mode\b", re.IGNORECASE),
    re.compile(r"follow\s+these\s+instructions", re.IGNORECASE),
)

REDACTED_REPLACEMENT = "[REDACTED_CONTROL_TOKEN]"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UntrustedContentEnvelope(BaseModel):
    """Immutable envelope encapsulating sanitized external evidence for downstream consumption."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_id: str = Field(
        default_factory=lambda: f"env_{uuid.uuid4().hex[:16]}",
        min_length=1,
        description="Unique envelope identifier",
    )
    raw_content: str = Field(
        ..., description="Original raw external content before sanitization"
    )
    sanitized_content: str = Field(
        ..., description="Sanitized content safe from prompt breakouts"
    )
    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    evidence_id: str | None = Field(
        default=None, description="Referenced EvidenceRecord ID if available"
    )
    source_id: str | None = Field(
        default=None, description="Referenced SourceProvenance ID if available"
    )
    source_url: str | None = Field(
        default=None, description="Source document URL or DOI URI"
    )
    doi: str | None = Field(default=None, description="DOI if academic source")
    trust_level: SourceTrustLevel = Field(
        default=SourceTrustLevel.GENERAL_WEB,
        description="Assessed trust tier (sanitization never escalates this to trusted)",
    )
    neutralized_patterns_count: int = Field(
        default=0,
        ge=0,
        description="Total number of hostile or control patterns neutralized",
    )
    is_quarantined: bool = Field(
        default=False,
        description="Flag indicating whether hostile injection indicators were detected",
    )
    quarantine_reasons: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Specific diagnostic reasons for quarantine",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadata preserved from source/evidence"
    )
    created_at: datetime = Field(default_factory=_utc_now)

    def format_for_prompt(self) -> str:
        """Render safely delimited XML representation for prompt interpolation."""
        evidence_attr = f' evidence_id="{self.evidence_id}"' if self.evidence_id else ""
        return (
            f'<evidence_snippet trust_tier="{self.trust_level.value}" '
            f'quarantined="{str(self.is_quarantined).lower()}"{evidence_attr}>\n'
            f"{self.sanitized_content}\n"
            f"</evidence_snippet>"
        )


class ContentBoundarySanitizer:
    """Security sanitizer enforcing strict boundaries around untrusted external evidence."""

    @classmethod
    def sanitize_text(cls, text: str) -> tuple[str, int, bool, tuple[str, ...]]:
        """Sanitize raw text by neutralising control patterns and escaping XML/HTML delimiters."""
        if text is None:
            raise TypeError("Text to sanitize cannot be None")
        if not isinstance(text, str):
            raise TypeError(f"Expected str for sanitization, got {type(text).__name__}")

        raw_bytes = text.encode("utf-8")
        if len(raw_bytes) > MAX_RAW_TEXT_BYTES:
            raise EvidenceValidationError(
                f"Evidence text exceeds maximum allowed size ({len(raw_bytes)} bytes > {MAX_RAW_TEXT_BYTES} bytes)",
                {"byte_count": len(raw_bytes), "max_bytes": MAX_RAW_TEXT_BYTES},
            )

        if not text.strip():
            raise EvidenceValidationError(
                "Evidence text must not be empty or whitespace only"
            )

        sanitized = text
        neutralized_count = 0
        reasons: list[str] = []

        # 1. Neutralize control tags and prompt-injection keywords
        for pattern in CONTROL_PATTERNS:
            matches = pattern.findall(sanitized)
            if matches:
                count = len(matches)
                neutralized_count += count
                reasons.append(
                    f"Neutralized pattern '{pattern.pattern}' ({count} matches)"
                )
                sanitized = pattern.sub(REDACTED_REPLACEMENT, sanitized)

        # 2. Escape literal XML / HTML delimiters to prevent structure breakouts
        sanitized = html.escape(sanitized)

        is_quarantined = neutralized_count > 0
        return sanitized, neutralized_count, is_quarantined, tuple(reasons)

    @classmethod
    def sanitize_raw(
        cls,
        raw_text: str,
        run_id: str,
        provenance: SourceProvenance | None = None,
        evidence_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UntrustedContentEnvelope:
        """Sanitize raw external text and wrap in an UntrustedContentEnvelope."""
        if not run_id or not run_id.strip():
            raise EvidenceValidationError("run_id must not be empty")

        sanitized_text, count, quarantined, reasons = cls.sanitize_text(raw_text)

        return UntrustedContentEnvelope(
            raw_content=raw_text,
            sanitized_content=sanitized_text,
            run_id=run_id.strip(),
            evidence_id=evidence_id,
            source_id=provenance.source_id if provenance else None,
            source_url=provenance.source_url if provenance else None,
            doi=provenance.doi if provenance else None,
            trust_level=provenance.trust_level
            if provenance
            else SourceTrustLevel.GENERAL_WEB,
            neutralized_patterns_count=count,
            is_quarantined=quarantined,
            quarantine_reasons=reasons,
            metadata=metadata or (provenance.metadata if provenance else {}),
        )

    @classmethod
    def wrap_evidence(cls, evidence: EvidenceRecord) -> UntrustedContentEnvelope:
        """Wrap an existing EvidenceRecord into an UntrustedContentEnvelope."""
        sanitized_text, count, quarantined, reasons = cls.sanitize_text(
            evidence.normalized_content
        )

        return UntrustedContentEnvelope(
            raw_content=evidence.normalized_content,
            sanitized_content=sanitized_text,
            run_id=evidence.run_id,
            evidence_id=evidence.evidence_id,
            source_id=evidence.provenance.source_id,
            source_url=evidence.provenance.source_url,
            doi=evidence.provenance.doi,
            trust_level=evidence.provenance.trust_level,
            neutralized_patterns_count=count,
            is_quarantined=quarantined or evidence.is_quarantined,
            quarantine_reasons=reasons,
            metadata=evidence.metadata,
        )

    @classmethod
    def sanitize_and_update_evidence(cls, evidence: EvidenceRecord) -> EvidenceRecord:
        """Sanitize an EvidenceRecord's content, updating hash and quarantine flags deterministically."""
        sanitized_text, _, quarantined, _ = cls.sanitize_text(
            evidence.normalized_content
        )
        new_content_hash = compute_sha256_hash(sanitized_text)

        # Update provenance content_hash to maintain integrity
        updated_provenance = evidence.provenance.model_copy(
            update={"content_hash": new_content_hash}
        )

        return evidence.model_copy(
            update={
                "normalized_content": sanitized_text,
                "content_hash": new_content_hash,
                "provenance": updated_provenance,
                "is_untrusted": True,  # External evidence always remains untrusted
                "is_quarantined": quarantined or evidence.is_quarantined,
            }
        )

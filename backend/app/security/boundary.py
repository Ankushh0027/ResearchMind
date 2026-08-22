"""Untrusted content boundaries, sanitization, and prompt injection quarantine."""

import html
import re
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import SourceTrustLevel


def _utc_now() -> datetime:
    return datetime.now(UTC)


# Patterns that attempt prompt instruction hijacking or XML delimiter breakouts
DANGEROUS_PATTERNS = [
    re.compile(r"<\s*/?\s*evidence_snippet\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*instruction\s*>", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+prompts", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+developer\s+mode", re.IGNORECASE),
]


class UntrustedContentEnvelope(BaseModel):
    """Quarantine envelope wrapping untrusted external document text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_id: str = Field(
        ..., min_length=1, description="Unique quarantine envelope ID"
    )
    raw_content: str = Field(..., description="Original raw external text")
    sanitized_content: str = Field(
        ..., description="Sanitized text safe for prompt interpolation"
    )
    trust_level: SourceTrustLevel = Field(
        default=SourceTrustLevel.GENERAL_WEB, description="Source trust category"
    )
    neutralized_patterns_count: int = Field(
        default=0, ge=0, description="Count of potentially hostile patterns neutralized"
    )
    is_quarantined: bool = Field(
        default=False, description="Whether hostile injection indicators were detected"
    )
    created_at: datetime = Field(default_factory=_utc_now)

    def format_for_prompt(self) -> str:
        """Render safely delimited XML representation for LLM prompt context."""
        return (
            f'<evidence_snippet trust_tier="{self.trust_level.value}" '
            f'quarantined="{str(self.is_quarantined).lower()}">\n'
            f"{self.sanitized_content}\n"
            f"</evidence_snippet>"
        )


class ContentBoundarySanitizer:
    """Sanitizer enforcing strict boundaries around external text to neutralize prompt injections."""

    @classmethod
    def sanitize(cls, text: str) -> tuple[str, int, bool]:
        """Sanitize text by escaping hazardous XML tags and detecting injection triggers."""
        # 1. HTML/XML entity escape potential tag brackets
        sanitized = text
        neutralized_count = 0
        is_quarantined = False

        for pattern in DANGEROUS_PATTERNS:
            matches = pattern.findall(sanitized)
            if matches:
                neutralized_count += len(matches)
                is_quarantined = True
                # Replace with harmless escaped representation
                sanitized = pattern.sub("[REDACTED_CONTROL_TOKEN]", sanitized)

        # 2. Escape literal xml-like tag delimiters
        sanitized = html.escape(sanitized)

        return sanitized, neutralized_count, is_quarantined

    @classmethod
    def wrap(
        cls,
        raw_text: str,
        trust_level: SourceTrustLevel = SourceTrustLevel.GENERAL_WEB,
    ) -> UntrustedContentEnvelope:
        """Wrap raw external text in an UntrustedContentEnvelope."""
        sanitized, count, quarantined = cls.sanitize(raw_text)
        return UntrustedContentEnvelope(
            envelope_id=f"env_{uuid.uuid4().hex[:12]}",
            raw_content=raw_text,
            sanitized_content=sanitized,
            trust_level=trust_level,
            neutralized_patterns_count=count,
            is_quarantined=quarantined,
        )

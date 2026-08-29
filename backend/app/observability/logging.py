"""Structured JSON logging with Google Cloud Logging correlation and secret scrubbing."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.observability.context import get_current_context


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# Regex patterns for credential and secret scrubbing
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE)
_GEMINI_KEY_PATTERN = re.compile(r"AIzaSy[A-Za-z0-9_\-]{33}")
_TAVILY_KEY_PATTERN = re.compile(r"tvly-[A-Za-z0-9_\-]{16,}")
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----[^-]+-----END [A-Z ]+PRIVATE KEY-----",
    re.DOTALL,
)
_PASSWORD_FIELD_PATTERN = re.compile(
    r'("?(?:password|api_key|secret|token|client_secret)"?\s*[:=]\s*["\'])([^"\']+)["\']',
    re.IGNORECASE,
)


class SecretScrubber:
    """Sanitizer stripping API keys, bearer tokens, private keys, and secrets from logs and telemetry."""

    @classmethod
    def scrub_text(cls, text: str) -> str:
        """Apply regex replacement rules to redact sensitive tokens in text."""
        if not text or not isinstance(text, str):
            return text

        scrubbed = _PRIVATE_KEY_PATTERN.sub("[REDACTED_PRIVATE_KEY]", text)
        scrubbed = _BEARER_PATTERN.sub(r"\1[REDACTED]", scrubbed)
        scrubbed = _GEMINI_KEY_PATTERN.sub("[REDACTED_GEMINI_KEY]", scrubbed)
        scrubbed = _TAVILY_KEY_PATTERN.sub("[REDACTED_TAVILY_KEY]", scrubbed)
        scrubbed = _PASSWORD_FIELD_PATTERN.sub(r"\1[REDACTED]", scrubbed)
        return scrubbed

    @classmethod
    def scrub_data(cls, data: Any) -> Any:
        """Recursively redact sensitive tokens in nested dictionaries, lists, and primitives."""
        if isinstance(data, str):
            return cls.scrub_text(data)
        if isinstance(data, dict):
            scrubbed_dict: dict[str, Any] = {}
            for k, v in data.items():
                lower_k = str(k).lower()
                if any(
                    secret_word in lower_k
                    for secret_word in (
                        "password",
                        "api_key",
                        "secret",
                        "authorization",
                        "private_key",
                        "token",
                    )
                ):
                    scrubbed_dict[k] = "[REDACTED]"
                else:
                    scrubbed_dict[k] = cls.scrub_data(v)
            return scrubbed_dict
        if isinstance(data, (list, tuple, set)):
            return [cls.scrub_data(item) for item in data]
        return data


class StructuredJsonLogFormatter(logging.Formatter):
    """Google Cloud Logging compatible single-line JSON log formatter with trace correlation."""

    def __init__(
        self,
        project_id: str | None = None,
        enable_scrubbing: bool = True,
    ) -> None:
        super().__init__()
        self._project_id = project_id
        self._enable_scrubbing = enable_scrubbing

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a structured JSON object."""
        message = record.getMessage()
        if self._enable_scrubbing:
            message = SecretScrubber.scrub_text(message)

        log_payload: dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
            "sourceLocation": {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Correlate with active distributed trace context
        context = get_current_context()
        if context is not None:
            trace_id = context.trace_id
            span_id = context.span_id
            if self._project_id:
                log_payload["logging.googleapis.com/trace"] = (
                    f"projects/{self._project_id}/traces/{trace_id}"
                )
            else:
                log_payload["logging.googleapis.com/trace"] = trace_id
            log_payload["logging.googleapis.com/spanId"] = span_id
            log_payload["logging.googleapis.com/trace_sampled"] = context.is_sampled

        # Include exception trace if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            if self._enable_scrubbing:
                exc_text = SecretScrubber.scrub_text(exc_text)
            log_payload["exception"] = exc_text

        # Merge custom extra dictionary fields
        for key, val in record.__dict__.items():
            if key not in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            ):
                scrubbed_val = (
                    SecretScrubber.scrub_data(val) if self._enable_scrubbing else val
                )
                log_payload[key] = scrubbed_val

        return json.dumps(log_payload, default=str)


__all__ = [
    "SecretScrubber",
    "StructuredJsonLogFormatter",
]

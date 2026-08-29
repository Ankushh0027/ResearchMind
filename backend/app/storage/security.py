"""Security validation utilities for artifact storage keys and paths."""

import posixpath
import re

from app.storage.protocols import InvalidObjectKeyError

# Allowed characters in object key path segments: alphanumeric, dashes, underscores, dots
_SAFE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def validate_object_key(run_id: str, object_key: str) -> str:
    """Validate that an object key is safe against path traversal and malformed inputs.

    Requirements:
    - Must not be empty or whitespace.
    - Must not contain null bytes or control characters.
    - Must not use Windows backslashes (normalized or rejected).
    - Must not contain directory traversal sequences ('..', './', '/.').
    - Must not start with a leading slash '/'.
    - Must not exceed 1024 characters.
    - Path segments must only contain safe alphanumeric, dash, underscore, and dot characters.

    Args:
        run_id: Associated research run identifier.
        object_key: Relative or scoped object key.

    Returns:
        The normalized POSIX object key.

    Raises:
        InvalidObjectKeyError: If the key violates any security constraints.
    """
    if not run_id or not run_id.strip():
        raise InvalidObjectKeyError("run_id cannot be empty or whitespace")

    if not object_key or not object_key.strip():
        raise InvalidObjectKeyError("object_key cannot be empty or whitespace")

    # Check for null bytes or control characters
    if "\x00" in object_key or any(ord(c) < 32 for c in object_key):
        raise InvalidObjectKeyError(
            "object_key contains forbidden control characters or null bytes"
        )

    # Check length
    if len(object_key) > 1024:
        raise InvalidObjectKeyError(
            f"object_key length ({len(object_key)}) exceeds maximum limit of 1024"
        )

    # Disallow backslashes
    if "\\" in object_key:
        raise InvalidObjectKeyError("object_key cannot contain backslashes")

    # Disallow leading slash
    if object_key.startswith("/"):
        raise InvalidObjectKeyError("object_key cannot start with a leading slash '/'")

    # Disallow directory traversal markers in raw key
    raw_segments = object_key.replace("\\", "/").split("/")
    if ".." in raw_segments:
        raise InvalidObjectKeyError(
            f"Directory traversal detected in object key: '{object_key}'"
        )

    # Normalize POSIX path
    normalized = posixpath.normpath(object_key)

    # Check for traversal escape or empty normalized path
    if (
        normalized in (".", "..")
        or normalized.startswith("../")
        or "/../" in normalized
        or "/.." in normalized
    ):
        raise InvalidObjectKeyError(
            f"Directory traversal detected in object key: '{object_key}'"
        )

    # Validate each segment
    segments = normalized.split("/")
    for segment in segments:
        if not segment or segment == ".":
            continue
        if segment == "..":
            raise InvalidObjectKeyError(
                f"Directory traversal detected in object key: '{object_key}'"
            )
        if not _SAFE_SEGMENT_RE.match(segment):
            raise InvalidObjectKeyError(
                f"Invalid characters in object key segment '{segment}'. "
                "Only alphanumeric, '-', '_', and '.' characters are allowed."
            )

    return normalized


__all__ = ["validate_object_key"]

"""ContextVar management for asynchronous trace and span propagation."""

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from app.observability.models import SpanContext

if TYPE_CHECKING:
    from app.observability.protocols import SpanProtocol

_ACTIVE_SPAN_VAR: ContextVar["SpanProtocol | None"] = ContextVar(
    "active_span", default=None
)
_ACTIVE_CONTEXT_VAR: ContextVar[SpanContext | None] = ContextVar(
    "active_context", default=None
)


def get_current_span() -> "SpanProtocol | None":
    """Return the currently active Span in the async execution context."""
    return _ACTIVE_SPAN_VAR.get()


def set_current_span(span: "SpanProtocol | None") -> Token["SpanProtocol | None"]:
    """Set the active Span in the async execution context."""
    return _ACTIVE_SPAN_VAR.set(span)


def reset_current_span(token: Token["SpanProtocol | None"]) -> None:
    """Reset the active Span to a previous token."""
    _ACTIVE_SPAN_VAR.reset(token)


def get_current_context() -> SpanContext | None:
    """Return the currently active SpanContext."""
    current_span = _ACTIVE_SPAN_VAR.get()
    if current_span is not None:
        return current_span.context
    return _ACTIVE_CONTEXT_VAR.get()


def set_current_context(context: SpanContext | None) -> Token[SpanContext | None]:
    """Set the active SpanContext."""
    return _ACTIVE_CONTEXT_VAR.set(context)


def reset_current_context(token: Token[SpanContext | None]) -> None:
    """Reset the active SpanContext to a previous token."""
    _ACTIVE_CONTEXT_VAR.reset(token)


__all__ = [
    "get_current_context",
    "get_current_span",
    "reset_current_context",
    "reset_current_span",
    "set_current_context",
    "set_current_span",
]

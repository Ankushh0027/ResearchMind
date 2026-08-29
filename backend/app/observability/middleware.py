"""ASGI/Starlette middleware for W3C distributed trace context extraction and injection."""

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

from app.observability.context import (
    reset_current_context,
    reset_current_span,
    set_current_context,
    set_current_span,
)
from app.observability.factory import get_tracer
from app.observability.models import (
    SpanContext,
    generate_span_id,
    generate_trace_id,
)


class TraceContextMiddleware(BaseHTTPMiddleware):
    """Extract or initialize W3C trace context, attach span, and populate response headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        tracer = get_tracer()
        headers = dict(request.headers)
        extracted_ctx = tracer.extract_context(headers)

        if extracted_ctx is None:
            extracted_ctx = SpanContext(
                trace_id=generate_trace_id(),
                span_id=generate_span_id(),
                trace_flags="01",
            )

        token_ctx = set_current_context(extracted_ctx)
        span = tracer.start_span(
            f"HTTP {request.method} {request.url.path}",
            parent=extracted_ctx,
            attributes={
                "http.method": request.method,
                "http.url": str(request.url.path),
                "http.client_ip": (
                    request.client.host if request.client else "unknown"
                ),
            },
        )
        token_span = set_current_span(span)

        try:
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            response.headers["X-Trace-ID"] = extracted_ctx.trace_id
            response.headers["traceparent"] = extracted_ctx.to_traceparent()
            return response
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            reset_current_span(token_span)
            reset_current_context(token_ctx)


__all__ = ["TraceContextMiddleware"]

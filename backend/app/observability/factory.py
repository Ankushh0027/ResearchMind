"""Factory methods for instantiating and managing the active TelemetryProvider."""

import logging

from app.config.settings import AppSettings, get_settings
from app.observability.metrics import InMemoryMetricsAccumulator
from app.observability.protocols import (
    MetricsProtocol,
    TelemetryProviderProtocol,
    TracerProtocol,
)
from app.observability.tracing import InMemoryTracer, OpenTelemetryTracer

logger = logging.getLogger(__name__)


class DefaultTelemetryProvider(TelemetryProviderProtocol):
    """Concrete container holding the active TracerProtocol and MetricsProtocol instances."""

    def __init__(
        self,
        tracer: TracerProtocol,
        metrics: MetricsProtocol,
    ) -> None:
        self._tracer = tracer
        self._metrics = metrics

    @property
    def tracer(self) -> TracerProtocol:
        return self._tracer

    @property
    def metrics(self) -> MetricsProtocol:
        return self._metrics

    def shutdown(self) -> None:
        pass


_GLOBAL_TELEMETRY_PROVIDER: TelemetryProviderProtocol | None = None


def create_telemetry_provider(
    settings: AppSettings | None = None,
) -> TelemetryProviderProtocol:
    """Create a configured TelemetryProviderProtocol based on application settings."""
    app_settings = settings or get_settings()

    metrics: MetricsProtocol = InMemoryMetricsAccumulator()
    tracer: TracerProtocol

    if getattr(app_settings, "otel_enabled", False):
        try:
            tracer = OpenTelemetryTracer(
                service_name=getattr(app_settings, "otel_service_name", "researchmind"),
                otlp_endpoint=getattr(
                    app_settings,
                    "otel_exporter_otlp_endpoint",
                    "http://localhost:4317",
                ),
                sampling_ratio=getattr(app_settings, "otel_sampling_ratio", 1.0),
            )
        except Exception as e:
            logger.warning(
                "Failed creating OpenTelemetryTracer (%s); falling back to InMemoryTracer.",
                e,
            )
            tracer = InMemoryTracer()
    else:
        tracer = InMemoryTracer()

    return DefaultTelemetryProvider(tracer=tracer, metrics=metrics)


def get_global_telemetry_provider() -> TelemetryProviderProtocol:
    """Return the active global telemetry provider, initializing default if needed."""
    global _GLOBAL_TELEMETRY_PROVIDER
    if _GLOBAL_TELEMETRY_PROVIDER is None:
        _GLOBAL_TELEMETRY_PROVIDER = create_telemetry_provider()
    return _GLOBAL_TELEMETRY_PROVIDER


def set_global_telemetry_provider(
    provider: TelemetryProviderProtocol | None,
) -> None:
    """Explicitly assign or reset the global telemetry provider."""
    global _GLOBAL_TELEMETRY_PROVIDER
    _GLOBAL_TELEMETRY_PROVIDER = provider


def get_tracer() -> TracerProtocol:
    """Convenience helper returning the tracer from the active global telemetry provider."""
    return get_global_telemetry_provider().tracer


def get_metrics() -> MetricsProtocol:
    """Convenience helper returning the metrics from the active global telemetry provider."""
    return get_global_telemetry_provider().metrics


__all__ = [
    "DefaultTelemetryProvider",
    "create_telemetry_provider",
    "get_global_telemetry_provider",
    "get_metrics",
    "get_tracer",
    "set_global_telemetry_provider",
]

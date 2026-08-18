"""OpenTelemetry tracing setup for the Airdrop Alpha backend.

Sets up a production-grade OTLP trace pipeline (batch exporter) with
FastAPI / httpx / APScheduler / sqlite3 / psycopg auto-instrumentation,
plus a shared ``tracer`` for manual spans (pipeline, per-agent).

Design (docs/OBSERVABILITY.md §4.2):
- Each pipeline run is a root span ``airdrop.pipeline.run`` with the
  ``run_id`` as a trace attribute.
- Each agent stage is a child span ``airdrop.agent.<name>``.
- All HTTP / DB / scheduler activity nested under those spans is captured
  automatically by the instrumentors below.

The only required knobs are standard OTel env vars, so the SDK can work in
any deployment (compose / k8s) without extra code:
- ``OTEL_ENABLED`` (bool, default false) -> master switch
- ``OTEL_EXPORTER_OTLP_ENDPOINT`` -> e.g. http://otel-collector:4317
- ``OTEL_SERVICE_NAME`` -> e.g. airdrop-alpha
- ``OTEL_TRACES_SAMPLER`` / ``OTEL_TRACES_SAMPLER_ARG`` -> sampling
"""

from __future__ import annotations

import logging
import os

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from app.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Global tracer for manual spans. Safe to use even when tracing is disabled:
# without a configured TracerProvider this returns a no-op tracer.
tracer = trace.get_tracer(__name__)

# Paths that generate noise rather than signal. Kept in sync with the
# Prometheus scrape whitelist so /metrics is neither scraped nor traced.
_EXCLUDED_PATHS = {"/health", "/metrics", "/version"}


def setup_tracing() -> bool:
    """Configure the OpenTelemetry SDK and auto-instrumentation.

    Returns:
        True when tracing was enabled, False when it stays a no-op
        (OTEL_ENABLED unset/false, e.g. local dev or tests).
    """
    if not settings.otel_enabled:
        return False

    try:
        # Let OTEL_SERVICE_NAME env override code default for deployment flexibility
        service_name = os.environ.get("OTEL_SERVICE_NAME") or settings.otel_service_name
        resource = Resource.create(
            {
                "service.name": service_name,
                # Mark traces that come from a real deployment; the value is
                # read from OTEL_DEPLOYMENT_ENVIRONMENT_NAME or APP_ENV.
                "deployment.environment": settings.app_env,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)

        # Re-bind global tracer once the provider is installed.
        global tracer
        tracer = trace.get_tracer(service_name)

        _instrument()
        logger.info(
            "tracing.enabled",
            endpoint=settings.otel_endpoint,
            service_name=service_name,
            sample_rate=settings.otel_sample_rate,
        )
        return True
    except Exception as exc:  # pragma: no cover - hard to trigger deterministically
        logger.error("tracing.setup_failed", error=str(exc), exc_info=True)
        return False


def instrument_fastapi_app(app) -> None:
    """Apply FastAPI instrumentation to a specific app instance.

    Must be called **after** the FastAPI app is created (and after all
    routes / middleware are registered) so that every request creates a
    server-side span with the correct context for child spans.
    """
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=",".join(_EXCLUDED_PATHS),
        )
        logger.info("tracing.fastapi_instrumented")
    except ImportError as exc:  # pragma: no cover - deps always installed
        logger.warning("tracing.fastapi_instrumentation_unavailable", missing=str(exc))


def _instrument() -> None:
    """Patch libraries for automatic spans (non-FastAPI instrumentors).

    httpx / DB instrumentors patch at the module level so the process-wide
    client / connection pool automatically get covered.
    """
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
        from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

        # httpx: outbound API calls made by fetchers / agents.
        HTTPXClientInstrumentor().instrument()

        # SQLite (dev) and PostgreSQL (prod) query spans.
        SQLite3Instrumentor().instrument()
        PsycopgInstrumentor().instrument()
    except ImportError as exc:  # pragma: no cover - deps always installed
        logger.warning("tracing.instrumentation_partial", missing=str(exc))


def span_attribute(key: str, value: object) -> None:
    """Attach an attribute to the current span (no-op when not tracing)."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute(key, value)


def end_span_with_error(span: trace.Span, exception: Exception) -> None:
    """Mark the span as failed and record the exception."""
    span.record_exception(exception)
    span.set_status(Status(StatusCode.ERROR))
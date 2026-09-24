"""Sink interface. A sink receives normalized, already-redacted events; it never sees raw payloads.

Implement `emit` for event-oriented backends (files, queues, log shippers). Span-oriented backends
(LangSmith, OpenTelemetry, ...) additionally implement `start_span` / `end_span` to build a run hierarchy.
Sinks must be cheap and non-blocking; the manager isolates their failures from the application.
"""
from abc import ABC, abstractmethod

from observability.context import Span
from observability.models import ObservabilityEvent


class ObservabilitySink(ABC):
    name: str = "sink"

    @abstractmethod
    def emit(self, event: ObservabilityEvent, span: Span | None) -> None:
        """Receive every event (span lifecycle events and point events)."""

    def start_span(self, span: Span, event: ObservabilityEvent) -> None:  # noqa: B027 - optional hook
        """Called when a span starts, after `emit` of its *_started event."""

    def end_span(self, span: Span, event: ObservabilityEvent) -> None:  # noqa: B027 - optional hook
        """Called when a span ends, after `emit` of its *_completed / *_failed event."""

    def flush(self, timeout: float | None = None) -> None:  # noqa: B027
        """Block until buffered events are delivered (best effort, bounded by `timeout`)."""

    def shutdown(self) -> None:  # noqa: B027
        """Flush and release resources. Must be idempotent."""

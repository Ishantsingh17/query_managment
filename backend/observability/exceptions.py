"""Structured exceptions. They are raised only when `OBSERVABILITY_FAIL_OPEN=false` (strict/dev mode);
in the default fail-open mode every observability failure is swallowed and reported as a warning."""


class ObservabilityError(Exception):
    """Base class for all observability failures."""


class ObservabilityConfigError(ObservabilityError):
    """Invalid or inconsistent observability configuration."""


class SinkError(ObservabilityError):
    """A sink (LangSmith, local file, ...) failed to accept an event."""

    def __init__(self, sink: str, message: str):
        super().__init__(f"[{sink}] {message}")
        self.sink = sink

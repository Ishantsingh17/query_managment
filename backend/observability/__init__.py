"""Reusable, framework-agnostic LLM observability.

    from observability import get_observability

    obs = get_observability()
    with obs.workflow("my_request", request_id=rid):
        with obs.agent("summarizer"):
            with obs.llm_call(component="summarizer", operation="summarize", provider="openai", model=m) as call:
                call.set_response(client.chat.completions.create(...))

Sinks: LangSmith (remote tracing) and a single local JSONL file. See README.md in this package.
"""
from observability.config import ObservabilitySettings
from observability.context import Span
from observability.enums import EventType, RunType, Status, UsageSource
from observability.exceptions import ObservabilityConfigError, ObservabilityError, SinkError
from observability.interfaces import ObservabilitySink
from observability.manager import (LlmCallHandle, ObservabilityManager, RetryHandle, SpanHandle, ToolCallHandle,
                                   configure_observability, get_observability, reset_observability)
from observability.models import ObservabilityEvent, TokenUsage
from observability.redaction import REDACTED, Redactor

__all__ = [
    "EventType", "LlmCallHandle", "ObservabilityConfigError", "ObservabilityError", "ObservabilityEvent",
    "ObservabilityManager", "ObservabilitySettings", "ObservabilitySink", "REDACTED", "Redactor", "RetryHandle",
    "RunType", "SinkError", "Span", "SpanHandle", "Status", "TokenUsage", "ToolCallHandle", "UsageSource",
    "configure_observability", "get_observability", "reset_observability",
]
__version__ = "1.0.0"

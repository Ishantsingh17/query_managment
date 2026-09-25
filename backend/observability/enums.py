"""Controlled vocabularies used by every observability event."""
from enum import Enum


class EventType(str, Enum):
    """Kinds of events written to every sink. Values are the strings that appear in the JSONL file."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"

    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    LLM_CALL_FAILED = "llm_call_failed"

    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"

    PROMPT_PREPARED = "prompt_prepared"
    RESPONSE_RECEIVED = "response_received"
    RESPONSE_PARSED = "response_parsed"

    RETRY_STARTED = "retry_started"
    RETRY_COMPLETED = "retry_completed"

    VALIDATION_EVENT = "validation_event"
    CORRELATION_LINKED = "correlation_linked"
    ERROR = "error"

    OBSERVABILITY_ERROR = "observability_error"


class RunType(str, Enum):
    """Generic classification of a span. Deliberately framework-neutral."""

    WORKFLOW = "workflow"
    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    EVENT = "event"  # point-in-time events that are not spans


class Status(str, Enum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
    INFO = "info"


class UsageSource(str, Enum):
    """Where token counts came from. Estimated values are never reported as provider values."""

    PROVIDER = "provider"
    ESTIMATED = "estimated"


# (started, completed, failed) event types for each span kind.
SPAN_EVENTS: dict[RunType, tuple[EventType, EventType, EventType]] = {
    RunType.WORKFLOW: (EventType.WORKFLOW_STARTED, EventType.WORKFLOW_COMPLETED, EventType.WORKFLOW_FAILED),
    RunType.AGENT: (EventType.AGENT_STARTED, EventType.AGENT_COMPLETED, EventType.AGENT_FAILED),
    RunType.LLM: (EventType.LLM_CALL_STARTED, EventType.LLM_CALL_COMPLETED, EventType.LLM_CALL_FAILED),
    RunType.TOOL: (EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_COMPLETED, EventType.TOOL_CALL_FAILED),
}

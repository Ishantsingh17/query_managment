"""Strongly typed event model shared by every sink.

One `ObservabilityEvent` == one JSON line in the local log. Field names are identical across event types;
fields that do not apply (or are unknown) are `None` — nothing is ever invented.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from observability.enums import EventType, RunType, Status, UsageSource
from observability.utils import iso_utc, new_id, utc_now


class TokenUsage(BaseModel):
    """Token usage for one LLM call. `source` distinguishes provider-reported from estimated counts."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(None, ge=0)
    output_tokens: int | None = Field(None, ge=0)
    total_tokens: int | None = Field(None, ge=0)
    cached_tokens: int | None = Field(None, ge=0)
    reasoning_tokens: int | None = Field(None, ge=0)
    source: UsageSource = UsageSource.PROVIDER
    details: dict[str, Any] = Field(default_factory=dict)  # provider-specific extras (already JSON-safe)

    @model_validator(mode="after")
    def _derive_total(self) -> "TokenUsage":
        if self.total_tokens is None and self.input_tokens is not None and self.output_tokens is not None:
            self.total_tokens = self.input_tokens + self.output_tokens
        return self

    @property
    def is_empty(self) -> bool:
        return all(v is None for v in (self.input_tokens, self.output_tokens, self.total_tokens))

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """Sum two usages (several model invocations inside one logical LLM call). Estimated + provider
        values are never silently mixed: the result is labelled `estimated` if either side is."""
        def add(a: int | None, b: int | None) -> int | None:
            return None if a is None and b is None else (a or 0) + (b or 0)
        return TokenUsage(
            input_tokens=add(self.input_tokens, other.input_tokens),
            output_tokens=add(self.output_tokens, other.output_tokens),
            total_tokens=add(self.total_tokens, other.total_tokens),
            cached_tokens=add(self.cached_tokens, other.cached_tokens),
            reasoning_tokens=add(self.reasoning_tokens, other.reasoning_tokens),
            source=UsageSource.ESTIMATED if UsageSource.ESTIMATED in (self.source, other.source) else UsageSource.PROVIDER,
            details={**self.details, **other.details},
        )


# Keys present on every JSON line (null when not applicable), so consumers can rely on a stable shape.
CORE_FIELDS = (
    "event_id", "timestamp", "event_type", "run_type", "name", "trace_id", "run_id", "parent_run_id", "request_id",
    "component", "operation", "provider", "model", "status", "latency_ms", "error_type", "error_message",
    "retry_count", "environment",
)
# Additionally always present on LLM events, so "no usage reported" is explicit (null) rather than absent.
LLM_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "usage_source", "input_captured", "output_captured")


class ObservabilityEvent(BaseModel):
    """A single normalized observability event."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # identity / correlation
    event_id: str = Field(default_factory=new_id)
    timestamp: datetime = Field(default_factory=utc_now)
    event_type: EventType
    run_type: RunType | None = None
    name: str | None = None
    trace_id: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    request_id: str | None = None
    linked_trace_id: str | None = None
    parent_llm_run_id: str | None = None
    framework_run_ids: list[str] | None = None

    # what
    component: str | None = None
    operation: str | None = None
    agent_name: str | None = None
    tool_name: str | None = None
    connector: str | None = None
    provider: str | None = None
    model: str | None = None
    status: Status | None = None

    # timing
    start_time: datetime | None = None
    end_time: datetime | None = None
    latency_ms: float | None = Field(None, ge=0)

    # usage / cost
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    usage_source: UsageSource | None = None
    usage_details: dict[str, Any] | None = None
    estimated_cost: float | None = None
    cost_currency: str | None = None
    pricing_source: str | None = None

    # errors / retries / fallbacks
    error_type: str | None = None
    error_message: str | None = None
    retry_count: int | None = Field(None, ge=0)
    retry_number: int | None = Field(None, ge=0)
    previous_error_type: str | None = None
    reason: str | None = None
    outcome: str | None = None

    # payloads (present only when capture is enabled; always redacted first)
    input_captured: bool | None = None
    output_captured: bool | None = None
    inputs: Any = None
    outputs: Any = None
    messages: list[Any] | None = None

    # free-form, JSON-safe, redacted
    attributes: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None

    environment: str | None = None
    service: str | None = None

    @field_serializer("timestamp", "start_time", "end_time")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return iso_utc(v) if v else None

    def to_record(self) -> dict[str, Any]:
        """JSON-ready dict: core (and, for LLM events, usage) keys always present; other keys only when set."""
        data = self.model_dump(mode="json")
        keep = set(CORE_FIELDS) | (set(LLM_FIELDS) if data.get("run_type") == RunType.LLM.value else set())
        return {k: v for k, v in data.items() if k in keep or v is not None}

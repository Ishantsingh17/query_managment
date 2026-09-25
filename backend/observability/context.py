"""Correlation context: spans, traces and their propagation via `contextvars`.

`contextvars` give each FastAPI request / asyncio task / copied thread context its own current span, so concurrent
requests never see each other's ids, and no global lock is held while application code runs.

Hierarchy:  request_id -> trace_id -> workflow run -> agent run -> llm run / tool run
Every span in a trace shares one `TraceState`, so a request id bound late (e.g. once the application has created
its request record) is carried by every subsequent event of that trace.
"""
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from observability.enums import RunType
from observability.models import TokenUsage
from observability.utils import new_id, perf_ms, utc_now


@dataclass
class TraceState:
    """State shared by every span of one trace."""

    trace_id: str
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Trace-wide roll-up: updated as each LLM/tool/agent span in the trace ends, read once when the
    # trace's root span ends to attach a whole-run summary (total tokens, cost, call counts, duration).
    start_perf: float = field(default_factory=perf_ms, repr=False)
    usage: TokenUsage | None = None
    estimated_cost: float | None = None
    cost_currency: str | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    agent_calls: int = 0

    def elapsed_ms(self) -> float:
        return round(max(0.0, perf_ms() - self.start_perf), 3)


@dataclass
class Span:
    """One unit of observed work (workflow, agent, LLM call or tool call)."""

    run_type: RunType
    name: str
    trace: TraceState
    run_id: str = field(default_factory=new_id)
    parent_run_id: str | None = None
    parent: "Span | None" = field(default=None, repr=False)
    component: str | None = None
    operation: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_name: str | None = None
    connector: str | None = None
    parent_llm_run_id: str | None = None
    retry_count: int | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=utc_now)
    start_perf: float = field(default_factory=perf_ms)
    # payloads kept in memory only; they reach sinks only if capture is enabled (and always redacted)
    inputs: Any = None
    outputs: Any = None
    messages: Any = None
    usage: TokenUsage | None = None
    framework_run_ids: list[str] = field(default_factory=list)
    status_override: str | None = None
    error: BaseException | None = None
    error_type: str | None = None
    error_message: str | None = None
    ended: bool = False
    sink_state: dict[str, Any] = field(default_factory=dict, repr=False)  # private per-sink bookkeeping
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def trace_id(self) -> str:
        return self.trace.trace_id

    @property
    def request_id(self) -> str | None:
        return self.trace.request_id

    @property
    def is_root(self) -> bool:
        return self.parent is None

    def elapsed_ms(self) -> float:
        return round(max(0.0, perf_ms() - self.start_perf), 3)

    def add_usage(self, usage: TokenUsage | None) -> None:
        if usage is None or usage.is_empty:
            return
        with self.lock:
            self.usage = usage if self.usage is None else self.usage + usage

    def ancestors(self) -> list["Span"]:
        out, cur = [], self.parent
        while cur is not None:
            out.append(cur)
            cur = cur.parent
        return out


_current_span: ContextVar[Span | None] = ContextVar("observability_current_span", default=None)
_current_retry: ContextVar[int | None] = ContextVar("observability_current_retry", default=None)
_current_llm_trigger: ContextVar[str | None] = ContextVar("observability_llm_trigger", default=None)


def current_span() -> Span | None:
    return _current_span.get()


def set_current_span(span: Span | None) -> Token:
    return _current_span.set(span)


def reset_current_span(token: Token) -> None:
    try:
        _current_span.reset(token)
    except ValueError:  # token created in another context (non-lexical start/end); fall back to parent
        span = _current_span.get()
        _current_span.set(span.parent if span is not None else None)


def current_retry_number() -> int | None:
    return _current_retry.get()


def set_retry_number(n: int | None) -> Token:
    return _current_retry.set(n)


def reset_retry_number(token: Token) -> None:
    try:
        _current_retry.reset(token)
    except ValueError:
        _current_retry.set(None)


def current_llm_trigger() -> str | None:
    return _current_llm_trigger.get()


def set_llm_trigger(run_id: str | None) -> Token:
    return _current_llm_trigger.set(run_id)


def reset_llm_trigger(token: Token) -> None:
    try:
        _current_llm_trigger.reset(token)
    except ValueError:
        _current_llm_trigger.set(None)

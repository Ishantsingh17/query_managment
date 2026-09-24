"""`ObservabilityManager`: the single entry point applications use.

Responsibilities: carry correlation ids (via `contextvars`), build normalized events, apply the capture policy and
redaction, fan events out to the configured sinks, and isolate every telemetry failure from the application
(fail-open). Application code never talks to LangSmith or the log file directly.

Typical use::

    obs = get_observability()
    with obs.workflow("audit_request", request_id=rid):
        with obs.agent("query_understanding"):
            with obs.llm_call(component="query_understanding", operation="structured_query",
                              provider="openai", model=model_name) as call:
                call.set_messages(messages)
                response = llm.invoke(messages)
                call.set_response(response)
"""
import asyncio
import atexit
import functools
import logging
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from observability.config import ObservabilitySettings
from observability.context import (Span, TraceState, current_llm_trigger, current_retry_number, current_span,
                                   reset_current_span, reset_llm_trigger, reset_retry_number, set_current_span,
                                   set_llm_trigger, set_retry_number)
from observability.enums import SPAN_EVENTS, EventType, RunType, Status, UsageSource
from observability.exceptions import ObservabilityError, SinkError
from observability.interfaces import ObservabilitySink
from observability.metrics import estimate_cost, estimate_usage, extract_response_model, extract_usage
from observability.models import ObservabilityEvent, TokenUsage
from observability.redaction import Redactor
from observability.serializers import describe_error, messages_to_list, to_jsonable
from observability.utils import enum_value, new_id, utc_now

log = logging.getLogger("observability")
F = TypeVar("F", bound=Callable[..., Any])

_EVENT_FIELDS = frozenset(ObservabilityEvent.model_fields)
_WARN_INTERVAL_S = 30.0


# =============================================================================================
# Handles returned by the context managers
# =============================================================================================

def _guard(fn: F) -> F:
    """Handle methods are telemetry: they must never raise into application code."""
    @functools.wraps(fn)
    def wrapper(self: "SpanHandle", *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._manager._internal_error(f"{type(self).__name__}.{fn.__name__}", exc)
            return None
    return wrapper  # type: ignore[return-value]


class SpanHandle:
    """Returned by `workflow()` / `agent()`; lets the caller annotate the running span."""

    def __init__(self, manager: "ObservabilityManager", span: Span):
        self._manager = manager
        self.span = span

    @property
    def run_id(self) -> str:
        return self.span.run_id

    @property
    def trace_id(self) -> str:
        return self.span.trace_id

    @property
    def request_id(self) -> str | None:
        return self.span.request_id

    @_guard
    def set_attribute(self, key: str, value: Any) -> None:
        self.span.attributes[key] = value

    @_guard
    def annotate(self, **attributes: Any) -> None:
        """Attach small, JSON-safe attributes (logged on the span's completion event)."""
        self.span.attributes.update(attributes)

    @_guard
    def set_metadata(self, **metadata: Any) -> None:
        self.span.metadata.update(metadata)

    @_guard
    def set_inputs(self, inputs: Any) -> None:
        """Logged only when OBSERVABILITY_CAPTURE_INPUTS=true (and always redacted)."""
        self.span.inputs = inputs

    @_guard
    def set_outputs(self, outputs: Any) -> None:
        """Logged only when OBSERVABILITY_CAPTURE_OUTPUTS=true (and always redacted)."""
        self.span.outputs = outputs

    @_guard
    def fail(self, error_type: str, message: str | None = None) -> None:
        """Mark the span failed without raising (e.g. a tool that returned an error result)."""
        self.span.status_override = Status.FAILED.value
        self.span.error_type, self.span.error_message = error_type, message

    @_guard
    def bind_request(self, request_id: str) -> None:
        self._manager.bind(request_id=request_id)


class LlmCallHandle(SpanHandle):
    """Returned by `llm_call()`."""

    @_guard
    def set_messages(self, messages: Any) -> None:
        """Prompt messages (system/user/tool). Logged only when OBSERVABILITY_CAPTURE_MESSAGES=true."""
        self.span.messages = messages
        self.span.attributes["message_count"] = len(messages) if isinstance(messages, (list, tuple)) else 1
        self._manager._step_event(EventType.PROMPT_PREPARED, self.span, {"message_count": self.span.attributes["message_count"]})

    @_guard
    def set_response(self, response: Any) -> None:
        """Raw provider/framework response: usage, model name and tool calls are extracted when available."""
        if not self.span.sink_state.get("_framework_usage"):
            self.span.add_usage(extract_usage(response))
        model = extract_response_model(response)
        if model:
            self.span.attributes["response_model"] = model
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls is not None:
            self.span.attributes["tool_call_count"] = len(tool_calls)
        if self.span.outputs is None:
            content = getattr(response, "content", None)
            self.span.outputs = ({"content": content, **({"tool_calls": [{"name": c.get("name"), "args": c.get("args")}
                                                                          for c in tool_calls]} if tool_calls else {})}
                                 if content is not None or tool_calls else response)
        self._manager._step_event(EventType.RESPONSE_RECEIVED, self.span, {"tool_call_count": len(tool_calls or [])})

    @_guard
    def set_output(self, output: Any) -> None:
        """Final (e.g. structured/parsed) output. Logged only when OBSERVABILITY_CAPTURE_OUTPUTS=true."""
        self.span.outputs = output

    @_guard
    def set_parsed(self, success: bool = True, error: BaseException | str | None = None) -> None:
        """Record the outcome of parsing/validating the model output."""
        self.span.attributes["parsed"] = success
        attrs: dict[str, Any] = {"parsed": success}
        if error is not None:
            et, msg = describe_error(error) if isinstance(error, BaseException) else ("ParseError", str(error))
            attrs.update(parse_error_type=et, parse_error_message=msg)
        self._manager._step_event(EventType.RESPONSE_PARSED, self.span, attrs)

    @_guard
    def set_usage(self, input_tokens: int | None = None, output_tokens: int | None = None,
                  total_tokens: int | None = None, cached_tokens: int | None = None,
                  reasoning_tokens: int | None = None, source: UsageSource | str = UsageSource.PROVIDER,
                  details: dict[str, Any] | None = None) -> None:
        """Explicit usage (for SDKs whose responses are not auto-detected). Replaces any auto-extracted usage."""
        self.span.usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
                                     cached_tokens=cached_tokens, reasoning_tokens=reasoning_tokens,
                                     source=UsageSource(source), details=details or {})

    @_guard
    def langchain_config(self) -> dict[str, Any]:
        """Optional RunnableConfig fragment (metadata/tags) to pass to `.invoke(..., config=...)`."""
        return {"metadata": self._manager.correlation_metadata(), "tags": list(self.span.tags)}


class ToolCallHandle(SpanHandle):
    """Returned by `tool_call()`."""

    @_guard
    def set_result(self, success: bool = True, error_type: str | None = None, error_message: str | None = None,
                   **attributes: Any) -> None:
        """Record the tool outcome. `success=False` marks the call failed without raising."""
        self.span.attributes.update(attributes)
        if not success:
            self.fail(error_type or "ToolError", error_message)


class RetryHandle:
    """Returned by `retry()`; spans started inside inherit `retry_count = retry_number`."""

    def __init__(self) -> None:
        self.outcome: str | None = None
        self.attributes: dict[str, Any] = {}

    def set_outcome(self, outcome: str, **attributes: Any) -> None:
        self.outcome = outcome
        self.attributes.update(attributes)


class _NoopHandle(LlmCallHandle, ToolCallHandle):
    """Used when observability is disabled or failed to start a span: accepts every call, does nothing."""

    def __init__(self) -> None:  # noqa: D107 - no manager/span
        pass

    def __getattribute__(self, name: str) -> Any:
        if name in ("run_id", "trace_id", "request_id"):
            return None
        if name.startswith("__"):
            return object.__getattribute__(self, name)
        if name == "langchain_config":
            return lambda: {}
        return lambda *a, **k: None


NOOP_HANDLE = _NoopHandle()


# =============================================================================================
# Manager
# =============================================================================================

class ObservabilityManager:
    """Framework-agnostic observability facade. Thread-safe; one instance per process is typical."""

    def __init__(self, settings: ObservabilitySettings | None = None, *, sinks: list[ObservabilitySink] | None = None,
                 redactor: Redactor | None = None, secrets: Iterable[str] = (), base_dir: str | Path | None = None,
                 install_integrations: bool = True):
        self.settings = settings or ObservabilitySettings.load()
        self.redactor = redactor or Redactor.from_settings(self.settings, secrets)
        self._base_dir = Path(base_dir) if base_dir else None
        self._warned: dict[str, float] = {}
        self._tls = threading.local()
        self.internal_error_count = 0
        self._sinks: list[ObservabilitySink] = list(sinks) if sinks is not None else self._default_sinks()
        self._closed = False
        if self.settings.config_errors:
            self._internal_error("configuration", ObservabilityError(
                "invalid settings: " + ", ".join(self.settings.config_errors)), strict=False)
        self._langchain = None
        if install_integrations and self.enabled:
            try:
                from observability.integrations import langchain as lc_integration
                if lc_integration.install():
                    self._langchain = lc_integration
            except Exception as exc:  # noqa: BLE001
                self._internal_error("langchain integration", exc, strict=False)

    # ---- construction -------------------------------------------------------------------------
    def _default_sinks(self) -> list[ObservabilitySink]:
        s = self.settings
        sinks: list[ObservabilitySink] = []
        if not s.enabled:
            return sinks
        if s.log_file_enabled:
            try:
                from observability.adapters.file_adapter import JsonlFileSink
                sinks.append(JsonlFileSink(s.resolved_log_file(self._base_dir), queue_size=s.queue_size,
                                           rotation_enabled=s.log_rotation_enabled, max_bytes=s.log_max_bytes,
                                           backup_count=s.log_backup_count))
            except Exception as exc:  # noqa: BLE001
                self._internal_error("file sink init", exc, strict=False)
        if s.langsmith_active:
            try:
                from observability.adapters.langsmith_adapter import LangSmithSink
                sinks.append(LangSmithSink(s, self.redactor))
            except Exception as exc:  # noqa: BLE001
                self._internal_error("langsmith sink init", exc, strict=False)
        elif s.langsmith_enabled and s.langsmith_tracing:
            self._warn_once("langsmith-no-key", "LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is not set; "
                                                "LangSmith tracing is disabled")
        return sinks

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled) and not self._closed

    @property
    def sinks(self) -> tuple[ObservabilitySink, ...]:
        return tuple(self._sinks)

    def sink(self, name: str) -> ObservabilitySink | None:
        return next((s for s in self._sinks if s.name == name), None)

    # ---- correlation --------------------------------------------------------------------------
    def current_span(self) -> Span | None:
        return current_span()

    def current_trace_id(self) -> str | None:
        span = current_span()
        return span.trace_id if span else None

    def current_run_id(self) -> str | None:
        span = current_span()
        return span.run_id if span else None

    def current_request_id(self) -> str | None:
        span = current_span()
        return span.request_id if span else None

    def correlation_metadata(self) -> dict[str, Any]:
        """Correlation ids for the current context, e.g. to pass as LangChain/LangGraph `config["metadata"]`."""
        span = current_span()
        if span is None:
            return {}
        md = {"request_id": span.request_id, "observability_trace_id": span.trace_id,
              "observability_run_id": span.run_id, "environment": self.settings.environment,
              "service": self.settings.service_name}
        return {k: v for k, v in md.items() if v is not None}

    def bind(self, request_id: str | None = None, **metadata: Any) -> None:
        """Attach a request id (and/or trace-wide metadata) to the current trace, e.g. once the application has
        created its request record. Every later event of the trace carries it; a `correlation_linked` event
        records the binding."""
        try:
            span = current_span()
            if span is None or not self.enabled:
                return
            with span.trace.lock:
                if request_id:
                    span.trace.request_id = request_id
                span.trace.metadata.update(metadata)
            if request_id:
                self._point(EventType.CORRELATION_LINKED, span, status=Status.INFO, reason="request_bound",
                            request_id=request_id)
        except Exception as exc:  # noqa: BLE001
            self._internal_error("bind", exc)

    def link_trace(self, linked_trace_id: str | None, *, request_id: str | None = None, reason: str | None = None,
                   **attributes: Any) -> None:
        """Record that `linked_trace_id` (e.g. an earlier analysis trace whose result was reused) belongs to the
        current trace / request."""
        if not linked_trace_id:
            return
        self._safe_point(EventType.CORRELATION_LINKED, status=Status.INFO, reason=reason or "trace_linked",
                         linked_trace_id=linked_trace_id, request_id=request_id, attributes=attributes or None)

    # ---- span context managers ---------------------------------------------------------------
    def workflow(self, name: str, *, request_id: str | None = None, operation: str | None = None,
                 inputs: Any = None, metadata: dict[str, Any] | None = None, tags: list[str] | None = None,
                 component: str | None = None) -> Any:
        """Top-level unit of work (a request / job). Starts a new trace unless nested in an existing one."""
        return self._span_cm(RunType.WORKFLOW, name, SpanHandle, request_id=request_id, operation=operation,
                             inputs=inputs, metadata=metadata, tags=tags, component=component or name)

    trace = workflow  # alias

    def agent(self, name: str, *, request_id: str | None = None, operation: str | None = None,
              component: str | None = None, inputs: Any = None, metadata: dict[str, Any] | None = None,
              tags: list[str] | None = None) -> Any:
        """An agent / pipeline step (LLM-backed or deterministic)."""
        return self._span_cm(RunType.AGENT, name, SpanHandle, request_id=request_id, operation=operation,
                             component=component or name, inputs=inputs, metadata=metadata, tags=tags)

    agent_run = agent  # alias

    def llm_call(self, *, component: str, operation: str, provider: str | None = None, model: str | None = None,
                 request_id: str | None = None, name: str | None = None, messages: Any = None, inputs: Any = None,
                 metadata: dict[str, Any] | None = None, tags: list[str] | None = None) -> Any:
        """One logical LLM call. Works with any SDK; LangChain calls inside are enriched automatically
        (usage, provider run ids) via the LangChain integration."""
        return self._span_cm(RunType.LLM, name or f"{component}.{operation}", LlmCallHandle, component=component,
                             operation=operation, provider=provider, model=model, request_id=request_id,
                             messages=messages, inputs=inputs, metadata=metadata, tags=tags)

    trace_llm = llm_call  # alias

    def tool_call(self, name: str, *, connector: str | None = None, component: str | None = None,
                  operation: str | None = None, request_id: str | None = None, inputs: Any = None,
                  parent_llm_run_id: str | None = None, retry_count: int | None = None,
                  metadata: dict[str, Any] | None = None, tags: list[str] | None = None) -> Any:
        """A tool / connector invocation (never classified as an LLM call)."""
        return self._span_cm(RunType.TOOL, name, ToolCallHandle, tool_name=name, connector=connector,
                             component=component, operation=operation, request_id=request_id, inputs=inputs,
                             parent_llm_run_id=parent_llm_run_id, retry_count=retry_count, metadata=metadata, tags=tags)

    @contextmanager
    def retry(self, *, component: str, operation: str, retry_number: int, reason: str | None = None,
              previous_error_type: str | None = None, **attributes: Any) -> Iterator[RetryHandle]:
        """Wrap one retry attempt: emits retry_started / retry_completed (same trace), and spans started inside
        carry `retry_count=retry_number`."""
        handle = RetryHandle()
        if not self.enabled:
            yield handle
            return
        common = dict(component=component, operation=operation, retry_number=retry_number, retry_count=retry_number,
                      previous_error_type=previous_error_type)
        self._safe_point(EventType.RETRY_STARTED, status=Status.STARTED, reason=reason, attributes=attributes or None,
                         **common)
        token = set_retry_number(retry_number)
        try:
            yield handle
        except BaseException as exc:
            et, msg = describe_error(exc)
            self._safe_point(EventType.RETRY_COMPLETED, status=Status.FAILED, outcome="exception", error_type=et,
                             error_message=msg, reason=reason, **common)
            raise
        else:
            self._safe_point(EventType.RETRY_COMPLETED, status=Status.SUCCESS if handle.outcome in (None, "success")
                             else Status.FAILED, outcome=handle.outcome or "success", reason=reason,
                             attributes={**attributes, **handle.attributes} or None, **common)
        finally:
            reset_retry_number(token)

    @contextmanager
    def triggered_by_llm(self, llm_run_id: str | None) -> Iterator[None]:
        """Tool calls started inside are recorded with `parent_llm_run_id=llm_run_id` (the LLM that requested them)."""
        token = set_llm_trigger(llm_run_id)
        try:
            yield
        finally:
            reset_llm_trigger(token)

    # ---- explicit (non-context-manager) API ---------------------------------------------------
    def start_trace(self, name: str, **fields: Any) -> Span | None:
        return self._start_explicit(RunType.WORKFLOW, name, **fields)

    def end_trace(self, span: Span | None, *, error: BaseException | None = None, outputs: Any = None) -> None:
        self._end_explicit(span, error=error, outputs=outputs)

    def start_agent(self, name: str, **fields: Any) -> Span | None:
        fields.setdefault("component", name)
        return self._start_explicit(RunType.AGENT, name, **fields)

    def end_agent(self, span: Span | None, *, error: BaseException | None = None, outputs: Any = None) -> None:
        self._end_explicit(span, error=error, outputs=outputs)

    def log_llm_start(self, *, component: str, operation: str, provider: str | None = None, model: str | None = None,
                      messages: Any = None, **fields: Any) -> Span | None:
        return self._start_explicit(RunType.LLM, fields.pop("name", None) or f"{component}.{operation}",
                                    component=component, operation=operation, provider=provider, model=model,
                                    messages=messages, **fields)

    def log_llm_end(self, span: Span | None, *, response: Any = None, usage: TokenUsage | None = None,
                    outputs: Any = None) -> None:
        if span is not None:
            h = LlmCallHandle(self, span)
            if response is not None:
                h.set_response(response)
            if usage is not None:
                span.usage = usage
        self._end_explicit(span, outputs=outputs)

    def log_llm_error(self, span: Span | None, error: BaseException) -> None:
        self._end_explicit(span, error=error)

    def log_tool_start(self, name: str, **fields: Any) -> Span | None:
        fields.setdefault("tool_name", name)
        return self._start_explicit(RunType.TOOL, name, **fields)

    def log_tool_end(self, span: Span | None, *, outputs: Any = None, **attributes: Any) -> None:
        if span is not None:
            span.attributes.update(attributes)
        self._end_explicit(span, outputs=outputs)

    def log_tool_error(self, span: Span | None, error: BaseException) -> None:
        self._end_explicit(span, error=error)

    # ---- point events -------------------------------------------------------------------------
    def log_event(self, event_type: EventType | str, *, status: Status | str = Status.INFO, **fields: Any) -> None:
        """Generic event attached to the current span. Unknown keyword fields go into `attributes`."""
        known = {k: v for k, v in fields.items() if k in _EVENT_FIELDS}
        extra = {k: v for k, v in fields.items() if k not in _EVENT_FIELDS}
        if extra:
            known["attributes"] = {**(known.get("attributes") or {}), **extra}
        self._safe_point(EventType(event_type), status=status, **known)

    def log_error(self, error: BaseException, *, component: str | None = None, operation: str | None = None,
                  **attributes: Any) -> None:
        """Record a handled error that does not end a span."""
        et, msg = describe_error(error)
        self._safe_point(EventType.ERROR, status=Status.FAILED, component=component, operation=operation,
                         error_type=et, error_message=msg, attributes=attributes or None)

    def log_retry_started(self, *, component: str, operation: str, retry_number: int, reason: str | None = None,
                          previous_error_type: str | None = None, **attributes: Any) -> None:
        self._safe_point(EventType.RETRY_STARTED, status=Status.STARTED, component=component, operation=operation,
                         retry_number=retry_number, retry_count=retry_number, reason=reason,
                         previous_error_type=previous_error_type, attributes=attributes or None)

    def log_retry_completed(self, *, component: str, operation: str, retry_number: int, outcome: str,
                            reason: str | None = None, **attributes: Any) -> None:
        self._safe_point(EventType.RETRY_COMPLETED, status=Status.SUCCESS if outcome == "success" else Status.FAILED,
                         component=component, operation=operation, retry_number=retry_number,
                         retry_count=retry_number, outcome=outcome, reason=reason, attributes=attributes or None)

    log_retry = log_retry_started

    def log_fallback_started(self, *, component: str, fallback_type: str, reason: str, operation: str | None = None,
                             error: BaseException | None = None, provider: str | None = None, model: str | None = None,
                             **attributes: Any) -> None:
        """The LLM path was abandoned (disabled / unavailable / failed) and a fallback takes over."""
        et, msg = describe_error(error)
        self._safe_point(EventType.LLM_FALLBACK_STARTED, status=Status.INFO, component=component, operation=operation,
                         fallback_type=fallback_type, reason=reason, error_type=et, error_message=msg,
                         provider=provider, model=model, attributes=attributes or None)

    def log_fallback_completed(self, *, component: str, fallback_type: str, reason: str | None = None,
                               operation: str | None = None, workflow_continued: bool = True,
                               success: bool = True, **attributes: Any) -> None:
        """The fallback produced its result. Makes it explicit that no LLM produced this output."""
        self._safe_point(EventType.LLM_FALLBACK_COMPLETED, status=Status.SUCCESS if success else Status.FAILED,
                         component=component, operation=operation, fallback_type=fallback_type, reason=reason,
                         workflow_continued=workflow_continued, outcome="success" if success else "failed",
                         attributes=attributes or None)

    def log_validation(self, name: str, *, outcome: str, component: str | None = None, **attributes: Any) -> None:
        """A validation / guardrail / quality-check result."""
        self._safe_point(EventType.VALIDATION_EVENT, status=Status.INFO, name=name, component=component or name,
                         outcome=outcome, attributes=attributes or None)

    # ---- decorator ----------------------------------------------------------------------------
    def observe(self, kind: RunType | str = RunType.AGENT, name: str | None = None, **fields: Any) -> Callable[[F], F]:
        """Decorator form of the span context managers (sync and async functions)."""
        run_type = RunType(kind)

        def deco(fn: F) -> F:
            span_name = name or fn.__qualname__

            def cm() -> Any:
                if run_type == RunType.WORKFLOW:
                    return self.workflow(span_name, **fields)
                if run_type == RunType.AGENT:
                    return self.agent(span_name, **fields)
                if run_type == RunType.TOOL:
                    return self.tool_call(span_name, **fields)
                if run_type == RunType.LLM:
                    return self.llm_call(name=span_name, **fields)
                raise ValueError(f"cannot observe run type {run_type}")

            if asyncio.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def awrapper(*args: Any, **kwargs: Any) -> Any:
                    with cm():
                        return await fn(*args, **kwargs)
                return awrapper  # type: ignore[return-value]

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with cm():
                    return fn(*args, **kwargs)
            return wrapper  # type: ignore[return-value]
        return deco

    # ---- lifecycle ----------------------------------------------------------------------------
    def flush(self, timeout: float | None = 5.0) -> None:
        for sink in self._sinks:
            try:
                sink.flush(timeout)
            except Exception as exc:  # noqa: BLE001
                self._internal_error(f"{sink.name}.flush", exc, strict=False)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        for sink in self._sinks:
            try:
                sink.shutdown()
            except Exception as exc:  # noqa: BLE001
                self._internal_error(f"{sink.name}.shutdown", exc, strict=False)

    # =========================================================================================
    # internals
    # =========================================================================================
    @contextmanager
    def _span_cm(self, run_type: RunType, name: str, handle_cls: type[SpanHandle], **fields: Any) -> Iterator[Any]:
        span = self._safe_start(run_type, name, **fields)
        if span is None:
            yield NOOP_HANDLE
            return
        token = set_current_span(span)
        lc_token = self._activate_langchain(span) if run_type == RunType.LLM else None
        try:
            yield handle_cls(self, span)
        except BaseException as exc:
            self._end_span(span, error=exc)
            raise
        else:
            self._end_span(span)
        finally:
            if lc_token is not None:
                self._deactivate_langchain(lc_token)
            reset_current_span(token)

    def _start_explicit(self, run_type: RunType, name: str, **fields: Any) -> Span | None:
        span = self._safe_start(run_type, name, **fields)
        if span is not None:
            span.sink_state["_ctx_token"] = set_current_span(span)
            if run_type == RunType.LLM:
                span.sink_state["_lc_token"] = self._activate_langchain(span)
        return span

    def _end_explicit(self, span: Span | None, *, error: BaseException | None = None, outputs: Any = None) -> None:
        if span is None:
            return
        if outputs is not None:
            span.outputs = outputs
        self._end_span(span, error=error)
        lc = span.sink_state.pop("_lc_token", None)
        if lc is not None:
            self._deactivate_langchain(lc)
        token = span.sink_state.pop("_ctx_token", None)
        if token is not None:
            reset_current_span(token)

    def _safe_start(self, run_type: RunType, name: str, **fields: Any) -> Span | None:
        if not self.enabled:
            return None
        try:
            return self._start_span(run_type, name, **fields)
        except Exception as exc:  # noqa: BLE001
            self._internal_error(f"start {run_type.value}", exc)
            return None

    def _start_span(self, run_type: RunType, name: str, *, request_id: str | None = None, inputs: Any = None,
                    messages: Any = None, metadata: dict[str, Any] | None = None, tags: list[str] | None = None,
                    retry_count: int | None = None, parent_llm_run_id: str | None = None, **fields: Any) -> Span:
        parent = current_span()
        if parent is not None and parent.ended:
            parent = None
        new_trace = parent is None or (run_type == RunType.WORKFLOW and request_id is not None
                                       and parent.request_id not in (None, request_id))
        run_id = new_id()
        if new_trace:
            parent = None
            # trace id == root run id, which is also the LangSmith trace id of the same trace
            trace = TraceState(trace_id=run_id, request_id=request_id)
        else:
            trace = parent.trace  # type: ignore[union-attr]
            if request_id and trace.request_id is None:
                with trace.lock:
                    trace.request_id = request_id
        if retry_count is None:
            retry_count = current_retry_number()
        if run_type == RunType.TOOL and parent_llm_run_id is None:
            parent_llm_run_id = current_llm_trigger()
        span = Span(run_type=run_type, name=name, trace=trace, parent=parent, run_id=run_id,
                    parent_run_id=parent.run_id if parent else None, inputs=inputs, messages=messages,
                    metadata=dict(metadata or {}), tags=list(tags or []), retry_count=retry_count,
                    parent_llm_run_id=parent_llm_run_id, **fields)
        event = self._span_event(span, SPAN_EVENTS[run_type][0], Status.STARTED)
        self._dispatch(event, span, phase="start")
        return span

    def _end_span(self, span: Span, error: BaseException | None = None) -> None:
        if span.ended:
            return
        span.ended = True
        try:
            if error is not None:
                span.error = error
            failed = error is not None or span.status_override == Status.FAILED.value
            started, completed, failed_type = SPAN_EVENTS[span.run_type]
            event = self._span_event(span, failed_type if failed else completed,
                                     Status.FAILED if failed else Status.SUCCESS, end=True)
            self._dispatch(event, span, phase="end")
        except Exception as exc:  # noqa: BLE001
            self._internal_error(f"end {span.run_type.value}", exc)

    def _span_event(self, span: Span, event_type: EventType, status: Status, end: bool = False) -> ObservabilityEvent:
        s = self.settings
        is_llm = span.run_type == RunType.LLM
        fields: dict[str, Any] = dict(
            event_type=event_type, run_type=span.run_type, name=span.name, trace_id=span.trace_id, run_id=span.run_id,
            parent_run_id=span.parent_run_id, request_id=span.request_id, component=span.component,
            operation=span.operation, provider=span.provider, model=span.model, tool_name=span.tool_name,
            connector=span.connector, parent_llm_run_id=span.parent_llm_run_id, status=status,
            retry_count=span.retry_count if span.retry_count is not None else (0 if span.run_type in (RunType.LLM, RunType.TOOL) else None),
            agent_name=span.name if span.run_type == RunType.AGENT else None,
            start_time=span.start_time, environment=s.environment, service=s.service_name,
        )
        if not end:
            fields["tags"] = span.tags or None
            fields["metadata"] = self._clean({**span.trace.metadata, **span.metadata}) or None
            if not is_llm and s.capture_inputs and span.inputs is not None:
                fields["inputs"] = self._clean(span.inputs)
            return self._build(fields)

        end_time = utc_now()
        fields.update(end_time=end_time, latency_ms=span.elapsed_ms(), attributes=self._clean(span.attributes) or None)
        if span.error is not None:
            fields["error_type"], fields["error_message"] = describe_error(span.error)
        elif span.error_type:
            fields["error_type"], fields["error_message"] = span.error_type, span.error_message
        if s.capture_outputs and span.outputs is not None:
            fields["outputs"] = self._clean(span.outputs)
        if is_llm:
            input_captured = False
            if s.capture_messages and span.messages is not None:
                fields["messages"] = self._clean(messages_to_list(span.messages))
                input_captured = True
            if s.capture_inputs and span.inputs is not None:
                fields["inputs"] = self._clean(span.inputs)
                input_captured = True
            fields["input_captured"] = input_captured
            fields["output_captured"] = "outputs" in fields
            fields["framework_run_ids"] = list(span.framework_run_ids) or None
            usage = span.usage
            if (usage is None or usage.is_empty) and s.token_estimation_enabled and span.error is None:
                usage = estimate_usage(span.messages if span.messages is not None else span.inputs, span.outputs)
            if usage is not None and not usage.is_empty:
                fields.update(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                              total_tokens=usage.total_tokens, cached_tokens=usage.cached_tokens,
                              reasoning_tokens=usage.reasoning_tokens, usage_source=usage.source,
                              usage_details=usage.details or None)
                cost = estimate_cost(usage, span.model, s)
                if cost is not None:
                    fields["estimated_cost"], fields["cost_currency"], fields["pricing_source"] = cost
        elif span.run_type == RunType.TOOL:
            fields["input_captured"] = bool(s.capture_inputs and span.inputs is not None)
            fields["output_captured"] = "outputs" in fields
        return self._build(fields)

    def _build(self, fields: dict[str, Any]) -> ObservabilityEvent:
        """Redact every free-text / payload field, then validate into the typed model."""
        r = self.redactor
        for key in ("error_message", "reason", "outcome", "previous_error_type"):
            if isinstance(fields.get(key), str):
                fields[key] = r.redact_text(fields[key])
        for key in ("inputs", "outputs", "messages", "attributes", "metadata", "tags"):
            if fields.get(key) is not None:
                fields[key] = r.redact(fields[key])
        return ObservabilityEvent(**fields)

    def _clean(self, value: Any) -> Any:
        return to_jsonable(value, self.settings.max_payload_chars)

    def _point(self, event_type: EventType, span: Span | None, *, status: Status | str, **fields: Any) -> None:
        base: dict[str, Any] = dict(event_type=event_type, run_type=RunType.EVENT, status=status,
                                    environment=self.settings.environment, service=self.settings.service_name)
        if span is not None:
            base.update(trace_id=span.trace_id, run_id=span.run_id, parent_run_id=span.parent_run_id,
                        request_id=span.request_id, component=span.component, operation=span.operation)
            if span.run_type == RunType.LLM:
                base.update(provider=span.provider, model=span.model)
        base.update({k: v for k, v in fields.items() if v is not None})
        if "attributes" in base:
            base["attributes"] = self._clean(base["attributes"])
        event = self._build(base)
        self._dispatch(event, span, phase="point")

    def _safe_point(self, event_type: EventType, *, status: Status | str = Status.INFO, **fields: Any) -> None:
        if not self.enabled:
            return
        try:
            self._point(event_type, current_span(), status=status, **fields)
        except Exception as exc:  # noqa: BLE001
            self._internal_error(f"event {enum_value(event_type)}", exc)

    def _step_event(self, event_type: EventType, span: Span, attributes: dict[str, Any]) -> None:
        if self.settings.llm_step_events and self.enabled:
            try:
                self._point(event_type, span, status=Status.INFO, attributes=attributes)
            except Exception as exc:  # noqa: BLE001
                self._internal_error(f"event {event_type.value}", exc)

    def _dispatch(self, event: ObservabilityEvent, span: Span | None, phase: str) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event, span)
                if span is not None and phase == "start":
                    sink.start_span(span, event)
                elif span is not None and phase == "end":
                    sink.end_span(span, event)
            except Exception as exc:  # noqa: BLE001 - a failing sink never affects the app or other sinks
                self._internal_error(f"sink {sink.name}", exc, failed_sink=sink)

    # ---- LangChain integration hooks ----------------------------------------------------------
    def _activate_langchain(self, span: Span) -> Any:
        if self._langchain is None:
            return None
        try:
            return self._langchain.activate(self, span)
        except Exception as exc:  # noqa: BLE001
            self._internal_error("langchain activate", exc)
            return None

    def _deactivate_langchain(self, token: Any) -> None:
        try:
            self._langchain.deactivate(token)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            self._internal_error("langchain deactivate", exc)

    # ---- failure handling ---------------------------------------------------------------------
    def _internal_error(self, where: str, exc: BaseException, *, failed_sink: ObservabilitySink | None = None,
                        strict: bool = True) -> None:
        """Fail-open: warn (rate-limited), record an `observability_error` event on the healthy sinks, continue.
        With OBSERVABILITY_FAIL_OPEN=false the error is re-raised (development/test strict mode)."""
        self.internal_error_count += 1
        et, msg = describe_error(exc)
        msg = self.redactor.redact_text(msg or "") if hasattr(self, "redactor") else msg
        self._warn_once(f"{where}:{et}", "observability failure in %s (%s: %s); application continues", where, et, msg)
        if not getattr(self._tls, "reporting", False) and getattr(self, "_sinks", None):
            self._tls.reporting = True
            try:
                span = current_span()
                event = ObservabilityEvent(
                    event_type=EventType.OBSERVABILITY_ERROR, run_type=RunType.EVENT, status=Status.FAILED,
                    trace_id=span.trace_id if span else None, run_id=span.run_id if span else None,
                    request_id=span.request_id if span else None, component="observability", operation=where,
                    error_type=et, error_message=msg, environment=self.settings.environment,
                    service=self.settings.service_name,
                    attributes={"sink": failed_sink.name} if failed_sink is not None else None)
                for sink in self._sinks:
                    if sink is failed_sink:
                        continue
                    try:
                        sink.emit(event, None)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                self._tls.reporting = False
        if strict and not self.settings.fail_open:
            if failed_sink is not None:
                raise SinkError(failed_sink.name, f"{et}: {msg}") from exc
            raise ObservabilityError(f"{where}: {et}: {msg}") from exc

    def _warn_once(self, key: str, msg: str, *args: Any) -> None:
        now = time.monotonic()
        if now - self._warned.get(key, -1e9) >= _WARN_INTERVAL_S:
            self._warned[key] = now
            log.warning(msg, *args)


# =============================================================================================
# Process-wide instance (like `logging`): justified because telemetry is cross-cutting and must be
# reachable from any layer without threading a parameter through every call.
# =============================================================================================

_global: ObservabilityManager | None = None
_global_lock = threading.Lock()


def configure_observability(settings: ObservabilitySettings | None = None, *, env_file: str | Path | None = None,
                            sinks: list[ObservabilitySink] | None = None, secrets: Iterable[str] = (),
                            base_dir: str | Path | None = None, redactor: Redactor | None = None) -> ObservabilityManager:
    """Create (or replace) the process-wide manager. Never raises in fail-open mode."""
    global _global
    try:
        settings = settings or ObservabilitySettings.load(env_file)
        manager = ObservabilityManager(settings, sinks=sinks, secrets=secrets, base_dir=base_dir, redactor=redactor)
    except Exception as exc:  # noqa: BLE001 - last line of defence: a disabled manager
        log.warning("observability could not be configured (%s); telemetry disabled", exc.__class__.__name__)
        manager = ObservabilityManager(ObservabilitySettings.model_construct(enabled=False), sinks=[],
                                       install_integrations=False)
    with _global_lock:
        old, _global = _global, manager
    if old is not None and old is not manager:
        old.shutdown()
    return manager


def get_observability() -> ObservabilityManager:
    """The process-wide manager, configured lazily from the environment on first use."""
    global _global
    if _global is None:
        with _global_lock:
            if _global is None:
                try:
                    _global = ObservabilityManager()
                except Exception as exc:  # noqa: BLE001
                    log.warning("observability disabled (%s)", exc.__class__.__name__)
                    _global = ObservabilityManager(ObservabilitySettings.model_construct(enabled=False), sinks=[],
                                                   install_integrations=False)
    return _global


def reset_observability() -> None:
    """Shut down and forget the process-wide manager (tests)."""
    global _global
    with _global_lock:
        old, _global = _global, None
    if old is not None:
        old.shutdown()


@atexit.register
def _shutdown_at_exit() -> None:
    if _global is not None:
        _global.shutdown()

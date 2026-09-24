"""LangChain integration: enrich `llm_call` spans from LangChain's own callback events — no pipeline rewrite.

`install()` registers a context-variable *configure hook* with LangChain (`register_configure_hook`, the same
mechanism LangChain uses for its tracers). While an `llm_call` span is active, the manager sets that variable to an
`ObservabilityCallbackHandler` bound to the span, so every LangChain chat model / LLM invoked inside the block
reports provider-side token usage, model name and its LangChain run id to the span — without passing callbacks
through application code.

This integration does NOT send anything to LangSmith itself: LangChain's native tracer does that (when the
LangSmith sink has an active trace), and the LangSmith sink then skips creating a second run for the same call.
"""
from contextvars import ContextVar, Token
from typing import Any

from observability.context import Span
from observability.metrics import extract_response_model, extract_usage

try:  # optional dependency
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tracers.context import register_configure_hook
    _AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    BaseCallbackHandler = object  # type: ignore[assignment,misc]
    _AVAILABLE = False

_handler_var: ContextVar[Any] = ContextVar("observability_langchain_handler", default=None)
_installed = False


def is_available() -> bool:
    return _AVAILABLE


def install() -> bool:
    """Register the configure hook once per process. Returns False when LangChain is not installed."""
    global _installed
    if not _AVAILABLE:
        return False
    if not _installed:
        register_configure_hook(_handler_var, inheritable=True)
        _installed = True
    return True


def activate(manager: Any, span: Span) -> Token | None:
    if not _installed:
        return None
    return _handler_var.set(ObservabilityCallbackHandler(manager, span))


def deactivate(token: Token | None) -> None:
    if token is None:
        return
    try:
        _handler_var.reset(token)
    except ValueError:
        _handler_var.set(None)


class ObservabilityCallbackHandler(BaseCallbackHandler):  # type: ignore[misc,valid-type]
    """Feeds LangChain model events into the active observability `llm_call` span."""

    raise_error = False  # a telemetry failure must never break the chain
    run_inline = True

    def __init__(self, manager: Any, span: Span):
        super().__init__()
        self.manager = manager
        self.span = span

    def _on_start(self, run_id: Any, metadata: dict[str, Any] | None, inputs: Any) -> None:
        try:
            span = self.span
            span.framework_run_ids.append(str(run_id))
            md = metadata or {}
            if span.provider is None and md.get("ls_provider"):
                span.provider = str(md["ls_provider"])
            if span.model is None and md.get("ls_model_name"):
                span.model = str(md["ls_model_name"])
            span.attributes.setdefault("framework", "langchain")
            span.attributes["llm_invocations"] = span.attributes.get("llm_invocations", 0) + 1
            if span.messages is None:
                span.messages = inputs
        except Exception as exc:  # noqa: BLE001
            self.manager._internal_error("langchain callback start", exc)

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: Any, metadata: dict | None = None,
                            **kwargs: Any) -> None:
        self._on_start(run_id, metadata, messages)

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: Any, metadata: dict | None = None,
                     **kwargs: Any) -> None:
        self._on_start(run_id, metadata, prompts)

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        try:
            usage = extract_usage(response)
            if usage is not None:
                self.span.add_usage(usage)
                self.span.sink_state["_framework_usage"] = True
            model = (getattr(response, "llm_output", None) or {}).get("model_name")
            if not model:
                gens = getattr(response, "generations", None) or []
                msg = getattr(gens[0][0], "message", None) if gens and gens[0] else None
                model = extract_response_model(msg)
                if self.span.outputs is None and msg is not None:
                    self.span.outputs = {"content": getattr(msg, "content", None)}
            if model:
                self.span.attributes["response_model"] = model
        except Exception as exc:  # noqa: BLE001
            self.manager._internal_error("langchain callback end", exc)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        try:
            self.span.attributes["provider_errors"] = self.span.attributes.get("provider_errors", 0) + 1
            self.span.attributes["last_provider_error_type"] = error.__class__.__name__
        except Exception as exc:  # noqa: BLE001
            self.manager._internal_error("langchain callback error", exc)

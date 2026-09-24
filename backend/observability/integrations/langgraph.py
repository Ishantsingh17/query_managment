"""LangGraph integration helpers.

* `graph_config()` — a RunnableConfig fragment for `graph.invoke(state, config=...)`: names the graph run and
  attaches correlation metadata (request id, trace id), which LangGraph/LangChain propagate to every child run
  in LangSmith, so native graph/node runs are searchable by request id.
* `observe_node()` — wraps a node function in an `agent` span, for nodes that represent meaningful agent steps.
  Do not wrap every node: deterministic plumbing nodes are better left unobserved to keep traces readable.
"""
import functools
from collections.abc import Callable, Mapping
from typing import Any

from observability.enums import RunType


def _manager(manager: Any) -> Any:
    if manager is not None:
        return manager
    from observability.manager import get_observability
    return get_observability()


def graph_config(manager: Any = None, *, run_name: str | None = None, tags: list[str] | None = None,
                 metadata: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """RunnableConfig with correlation metadata for the current observability context."""
    try:
        md = {**_manager(manager).correlation_metadata(), **(metadata or {})}
    except Exception:  # noqa: BLE001 - telemetry must not break graph execution
        md = dict(metadata or {})
    cfg: dict[str, Any] = {"metadata": md, **extra}
    if run_name:
        cfg["run_name"] = run_name
    if tags:
        cfg["tags"] = list(tags)
    return cfg


def observe_node(name: str, *, manager: Any = None, component: str | None = None, operation: str | None = None,
                 request_id_key: str = "request_id", kind: RunType | str = RunType.AGENT) -> Callable:
    """Decorator: run a LangGraph node inside an `agent` (or `workflow`) span named `name`.

    The request id is read from `state[request_id_key]` when present. The node's signature is preserved
    (`functools.wraps`), so LangGraph's config/store injection keeps working.
    """
    run_type = RunType(kind)

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: Any, *args: Any, **kwargs: Any) -> Any:
            obs = _manager(manager)
            rid = state.get(request_id_key) if isinstance(state, Mapping) else getattr(state, request_id_key, None)
            cm = (obs.workflow(name, request_id=rid, operation=operation, component=component) if run_type == RunType.WORKFLOW
                  else obs.agent(name, request_id=rid, operation=operation, component=component))
            with cm as span:
                result = fn(state, *args, **kwargs)
                if isinstance(result, Mapping):
                    span.annotate(updated_state_keys=sorted(map(str, result)))
                return result
        return wrapper
    return deco

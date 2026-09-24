"""Generic helpers for LLM calls made with any SDK (OpenAI, Anthropic, Groq, Bedrock, HTTP, ...).

Usage is auto-extracted from common response shapes (`.usage`, `.usage_metadata`); for anything else call
`call.set_usage(...)` inside `obs.llm_call(...)` yourself.
"""
import functools
import inspect
from collections.abc import Callable
from typing import Any


def _manager(manager: Any) -> Any:
    if manager is not None:
        return manager
    from observability.manager import get_observability
    return get_observability()


def call_llm(fn: Callable[..., Any], *args: Any, component: str, operation: str, provider: str | None = None,
             model: str | None = None, messages: Any = None, manager: Any = None, **kwargs: Any) -> Any:
    """Invoke `fn(*args, **kwargs)` as one observed LLM call and return its result unchanged."""
    with _manager(manager).llm_call(component=component, operation=operation, provider=provider, model=model) as call:
        if messages is not None:
            call.set_messages(messages)
        result = fn(*args, **kwargs)
        call.set_response(result)
        return result


def observed_llm(*, component: str, operation: str, provider: str | None = None, model: str | None = None,
                 messages_arg: str | None = None, manager: Any = None) -> Callable:
    """Decorator for a function that performs one LLM call and returns the provider response.

    `messages_arg` names the parameter holding the prompt messages (captured only if message capture is on).
    """
    def deco(fn: Callable) -> Callable:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _manager(manager).llm_call(component=component, operation=operation, provider=provider,
                                            model=model) as call:
                if messages_arg:
                    try:
                        call.set_messages(sig.bind_partial(*args, **kwargs).arguments.get(messages_arg))
                    except TypeError:
                        pass
                result = fn(*args, **kwargs)
                call.set_response(result)
                return result
        return wrapper
    return deco

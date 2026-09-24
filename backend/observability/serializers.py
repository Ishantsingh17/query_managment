"""Safe, bounded conversion of arbitrary Python objects into JSON-compatible values.

Never raises: anything that cannot be serialized becomes a short descriptive string. Strings are truncated to
`max_chars`, containers to `max_items`, nesting to `max_depth`, so huge prompts/objects cannot bloat the log.
"""
import dataclasses
import enum
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

from observability.utils import iso_utc

MAX_ITEMS = 200
MAX_DEPTH = 12
ERROR_MESSAGE_CHARS = 500


def _truncate(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[:max_chars] + f"...[truncated {len(s) - max_chars} chars]"


def to_jsonable(obj: Any, max_chars: int = 4000, max_depth: int = MAX_DEPTH, _depth: int = 0) -> Any:
    """Best-effort JSON-safe copy of `obj`."""
    try:
        if obj is None or isinstance(obj, (bool, int)):
            return obj
        if isinstance(obj, float):
            return obj if math.isfinite(obj) else str(obj)
        if isinstance(obj, str):
            return _truncate(obj, max_chars)
        if isinstance(obj, enum.Enum):
            return to_jsonable(obj.value, max_chars, max_depth, _depth)
        if isinstance(obj, datetime):
            return iso_utc(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, (UUID, PurePath)):
            return str(obj)
        if isinstance(obj, (bytes, bytearray, memoryview)):
            return f"<bytes len={len(obj)}>"
        if _depth >= max_depth:
            return f"<{type(obj).__name__} depth-limit>"
        nxt = _depth + 1
        if _is_message(obj):
            return to_jsonable(message_to_dict(obj), max_chars, max_depth, nxt)
        if isinstance(obj, Mapping):
            items = list(obj.items())
            out = {str(k): to_jsonable(v, max_chars, max_depth, nxt) for k, v in items[:MAX_ITEMS]}
            if len(items) > MAX_ITEMS:
                out["__truncated_items__"] = len(items) - MAX_ITEMS
            return out
        if isinstance(obj, (list, tuple, set, frozenset)):
            seq = list(obj)
            out_list = [to_jsonable(v, max_chars, max_depth, nxt) for v in seq[:MAX_ITEMS]]
            if len(seq) > MAX_ITEMS:
                out_list.append(f"...[{len(seq) - MAX_ITEMS} more items]")
            return out_list
        dump = getattr(obj, "model_dump", None)  # pydantic v2
        if callable(dump):
            return to_jsonable(dump(), max_chars, max_depth, nxt)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return to_jsonable({f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}, max_chars, max_depth, nxt)
        return _truncate(f"<{type(obj).__name__}>", max_chars)
    except Exception:  # noqa: BLE001 - serialization must never break the caller
        return f"<unserializable {type(obj).__name__}>"


def _is_message(obj: Any) -> bool:
    """Duck-typed chat message (LangChain BaseMessage and similar): has `type` and `content`."""
    return not isinstance(obj, (Mapping, str, type)) and hasattr(obj, "content") and hasattr(obj, "type")


def message_to_dict(msg: Any) -> dict[str, Any]:
    """Normalize one chat message (LangChain message, (role, content) tuple, or dict) to {role, content, ...}."""
    if isinstance(msg, Mapping):
        return {"role": msg.get("role") or msg.get("type"), "content": msg.get("content"),
                **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {})}
    if isinstance(msg, tuple) and len(msg) == 2:
        return {"role": str(msg[0]), "content": msg[1]}
    if _is_message(msg):
        out: dict[str, Any] = {"role": getattr(msg, "type", None), "content": getattr(msg, "content", None)}
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            out["tool_calls"] = [{"name": c.get("name"), "args": c.get("args"), "id": c.get("id")} for c in tool_calls]
        if getattr(msg, "tool_call_id", None):
            out["tool_call_id"] = msg.tool_call_id
        return out
    return {"role": None, "content": str(msg)}


def messages_to_list(messages: Any) -> list[dict[str, Any]]:
    if messages is None:
        return []
    if isinstance(messages, (str, bytes)) or not isinstance(messages, (list, tuple)):
        return [{"role": "user", "content": messages if isinstance(messages, str) else str(messages)}]
    if messages and isinstance(messages[0], list):  # LangChain callbacks pass list[list[BaseMessage]]
        messages = [m for batch in messages for m in batch]
    return [message_to_dict(m) for m in messages]


def describe_error(exc: BaseException | None) -> tuple[str | None, str | None]:
    """(error_type, bounded message). The message is redacted by the manager before it reaches any sink."""
    if exc is None:
        return None, None
    msg = str(exc) or exc.__class__.__name__
    return exc.__class__.__name__, _truncate(msg.replace("\r", " ").replace("\n", " "), ERROR_MESSAGE_CHARS)


def dumps_line(record: Mapping[str, Any]) -> str:
    """One compact JSON line (no embedded newlines, ASCII-safe)."""
    return json.dumps(record, ensure_ascii=True, separators=(",", ":"), default=str)

"""Small shared helpers (ids, clocks, timestamps)."""
import time
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """Random UUID4 string. Run ids are UUIDs so they can be reused verbatim as LangSmith run ids."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """ISO-8601 UTC with millisecond precision and a `Z` suffix, e.g. 2026-09-24T12:30:45.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def perf_ms() -> float:
    """Monotonic clock in milliseconds (for latency, immune to wall-clock changes)."""
    return time.perf_counter() * 1000.0


def enum_value(v: object) -> object:
    """`Enum.value` for enum members, the object itself otherwise (note: `str(StrEnumMember)` is NOT its value)."""
    from enum import Enum
    return v.value if isinstance(v, Enum) else v

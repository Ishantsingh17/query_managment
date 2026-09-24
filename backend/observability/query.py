"""Offline querying of the local JSONL log (debugging, tests, support).

    python -m observability.query logs/llm_observability.jsonl --request-id REQ-1001
    python -m observability.query logs/llm_observability.jsonl --trace-id <uuid> --event-type llm_call_completed

Request correlation includes traces that were *linked* to the request (`correlation_linked` events), so a request
whose LLM understanding ran in an earlier analysis trace still shows that LLM activity.
"""
import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


def iter_events(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield every valid JSON line; invalid lines are skipped (see `validate_file`)."""
    p = Path(path)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def validate_file(path: str | Path) -> tuple[int, list[int]]:
    """(valid line count, 1-based numbers of invalid lines)."""
    valid, invalid = 0, []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            try:
                if isinstance(json.loads(line), dict):
                    valid += 1
                    continue
            except json.JSONDecodeError:
                pass
            invalid.append(i)
    return valid, invalid


def trace_ids_for_request(events: Iterable[dict[str, Any]], request_id: str) -> set[str]:
    traces: set[str] = set()
    for e in events:
        if e.get("request_id") == request_id:
            if e.get("trace_id"):
                traces.add(e["trace_id"])
            if e.get("linked_trace_id"):
                traces.add(e["linked_trace_id"])
    return traces


def read_events(path: str | Path, *, request_id: str | None = None, trace_id: str | None = None,
                event_types: Iterable[str] | None = None, run_type: str | None = None) -> list[dict[str, Any]]:
    """Events filtered by request (incl. linked traces), trace, event type and/or run type, in file order."""
    events = list(iter_events(path))
    if request_id is not None:
        traces = trace_ids_for_request(events, request_id)
        events = [e for e in events if e.get("request_id") == request_id or e.get("trace_id") in traces]
    if trace_id is not None:
        events = [e for e in events if e.get("trace_id") == trace_id]
    if event_types is not None:
        wanted = set(event_types)
        events = [e for e in events if e.get("event_type") in wanted]
    if run_type is not None:
        events = [e for e in events if e.get("run_type") == run_type]
    return events


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Query the local LLM observability JSONL log")
    ap.add_argument("path")
    ap.add_argument("--request-id")
    ap.add_argument("--trace-id")
    ap.add_argument("--event-type", action="append")
    ap.add_argument("--run-type")
    ap.add_argument("--validate", action="store_true", help="only check that every line is valid JSON")
    a = ap.parse_args(argv)
    if a.validate:
        valid, invalid = validate_file(a.path)
        print(json.dumps({"valid_lines": valid, "invalid_lines": invalid}))
        return 1 if invalid else 0
    for e in read_events(a.path, request_id=a.request_id, trace_id=a.trace_id, event_types=a.event_type,
                         run_type=a.run_type):
        print(json.dumps(e, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

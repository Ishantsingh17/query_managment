"""Local JSON Lines sink: ONE append-only file, one JSON object per line.

Concurrency: application threads only serialize the event and `put_nowait` it on a *bounded* queue; a single
background writer thread owns the file handle and appends whole lines. No lock is held around application work,
lines can never interleave, and a full queue drops events (counted and warned about) instead of blocking an LLM call.

Rotation (off by default, `OBSERVABILITY_LOG_ROTATION_ENABLED=true`): size-based and bounded. When the active file
would exceed `OBSERVABILITY_LOG_MAX_BYTES`, it is renamed to `<file>.1` (existing `.1` -> `.2`, ...) and a fresh
`<file>` is started; at most `OBSERVABILITY_LOG_BACKUP_COUNT` backups are kept, the oldest is deleted. The logical
destination stays the configured path; no per-request/per-day/per-agent files are ever created.
"""
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import IO

from observability.context import Span
from observability.interfaces import ObservabilitySink
from observability.models import ObservabilityEvent
from observability.serializers import dumps_line

log = logging.getLogger("observability")

_STOP = object()
_BATCH = 500
_WARN_INTERVAL_S = 30.0


class JsonlFileSink(ObservabilitySink):
    name = "file"

    def __init__(self, path: str | Path, *, queue_size: int = 10_000, rotation_enabled: bool = False,
                 max_bytes: int = 50 * 1024 * 1024, backup_count: int = 5):
        self.path = Path(path)
        self.rotation_enabled = rotation_enabled
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._fh: IO[str] | None = None
        self._size = 0
        self._closed = False
        self._last_warn = 0.0
        self.dropped_events = 0
        self.write_failures = 0
        self._thread = threading.Thread(target=self._run, name="observability-jsonl-writer", daemon=True)
        self._thread.start()

    # ---- producer side (application threads) --------------------------------------------------
    def emit(self, event: ObservabilityEvent, span: Span | None) -> None:
        if self._closed:
            return
        line = dumps_line(event.to_record())
        try:
            self._queue.put_nowait(line)
        except queue.Full:
            self.dropped_events += 1
            self._warn("observability log queue full; dropped %d event(s) so far", self.dropped_events)

    def flush(self, timeout: float | None = 5.0) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        q = self._queue
        with q.all_tasks_done:
            while q.unfinished_tasks:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return
                q.all_tasks_done.wait(remaining)

    def shutdown(self) -> None:
        if self._closed:
            return
        self.flush(5.0)
        self._closed = True
        try:
            self._queue.put(_STOP, timeout=1.0)
        except queue.Full:
            pass
        self._thread.join(timeout=5.0)
        self._close_file()

    # ---- writer thread ------------------------------------------------------------------------
    def _run(self) -> None:
        while True:
            item = self._queue.get()
            batch, stop = [], item is _STOP
            if not stop:
                batch.append(item)
            while not stop and len(batch) < _BATCH:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _STOP:
                    stop = True
                else:
                    batch.append(nxt)
            try:
                if batch:
                    self._write(batch)
            finally:
                for _ in range(len(batch) + (1 if stop else 0)):
                    self._queue.task_done()
            if stop:
                return

    def _open(self) -> IO[str]:
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8", newline="\n")  # noqa: SIM115 - long-lived handle
            self._size = self._fh.tell()
        return self._fh

    def _write(self, lines: list[str]) -> None:
        data = "".join(line + "\n" for line in lines)
        try:
            fh = self._open()
            if self.rotation_enabled and self._size > 0 and self._size + len(data) > self.max_bytes:
                self._rollover()
                fh = self._open()
            fh.write(data)
            fh.flush()
            self._size += len(data.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - never propagate into the application
            self.write_failures += 1
            self._close_file()
            self._warn("observability log write failed (%s: %s); %d event(s) lost",
                       exc.__class__.__name__, exc, len(lines))

    def _rollover(self) -> None:
        self._close_file()
        for i in range(self.backup_count - 1, 0, -1):
            src, dst = self.path.with_name(f"{self.path.name}.{i}"), self.path.with_name(f"{self.path.name}.{i + 1}")
            if src.exists():
                os.replace(src, dst)
        if self.path.exists():
            os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))

    def _close_file(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None

    def _warn(self, msg: str, *args: object) -> None:
        now = time.monotonic()
        if now - self._last_warn >= _WARN_INTERVAL_S:
            self._last_warn = now
            log.warning(msg, *args)

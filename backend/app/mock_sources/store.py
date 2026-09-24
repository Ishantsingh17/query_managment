"""SQLite store behind the mock source APIs. Kept separate from the Request DB so the retrieval
path can only reach source data through the API boundary."""
from pathlib import Path
from threading import Lock

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, select, update
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.mock_sources.datasets import OBJECTS, SOURCE_SYSTEMS, ObjectSpec

metadata = MetaData()
_tables: dict[str, Table] = {}
_engine: Engine | None = None
_lock = Lock()

source_status = Table(
    "source_status", metadata,
    Column("source_system", String, primary_key=True),
    Column("display_name", String, nullable=False),
    Column("available", Boolean, nullable=False, default=True),
)

# Per-request lookup counts for "posted late" rows: a late record is hidden on the first lookup(s) *of each request*
# and visible on that request's retry, so the late-posting demo works for every new request (no manual reset).
late_posting_calls = Table(
    "late_posting_calls", metadata,
    Column("table_name", String, primary_key=True),
    Column("row_id", Integer, primary_key=True),
    Column("request_id", String, primary_key=True),
    Column("call_count", Integer, nullable=False, default=0),
)

for _spec in OBJECTS:
    cols = [Column("_row_id", Integer, primary_key=True, autoincrement=True), Column("_call_count", Integer, default=0)]
    cols += [Column(c, String) for c in _spec.columns]
    _tables[_spec.table] = Table(_spec.table, metadata, *cols)


def get_source_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().source_db_url
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, connect_args={"check_same_thread": False})
    return _engine


def reset_source_engine(url: str | None = None) -> None:
    global _engine
    _engine = create_engine(url, connect_args={"check_same_thread": False}) if url else None


def seed_sources(force: bool = False) -> None:
    """(Re)create the mock source datasets."""
    engine = get_source_engine()
    with _lock:
        if force:
            metadata.drop_all(engine)
        metadata.create_all(engine)
        with engine.begin() as conn:
            if conn.execute(select(source_status)).first() and not force:
                return
            conn.execute(source_status.delete())
            for code, name in SOURCE_SYSTEMS.items():
                conn.execute(source_status.insert().values(source_system=code, display_name=name, available=True))
            for spec in OBJECTS:
                table = _tables[spec.table]
                conn.execute(table.delete())
                for row in spec.rows:
                    conn.execute(table.insert().values(_call_count=0, **{k: None if v is None else str(v) for k, v in row.items()}))


def is_source_available(source: str) -> bool:
    with get_source_engine().connect() as conn:
        row = conn.execute(select(source_status.c.available).where(source_status.c.source_system == source)).first()
        return bool(row and row[0])


def set_source_available(source: str, available: bool) -> None:
    with get_source_engine().begin() as conn:
        conn.execute(update(source_status).where(source_status.c.source_system == source).values(available=available))


def list_sources() -> list[dict]:
    with get_source_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(source_status))]


def reset_late_postings() -> int:
    """Re-arm 'posted late' rows (visible_after_calls) so the retry scenarios can be demonstrated again."""
    n = 0
    with _lock, get_source_engine().begin() as conn:
        for table in _tables.values():
            n += conn.execute(update(table).values(_call_count=0)).rowcount or 0
        conn.execute(late_posting_calls.delete())
    return n


def query(spec: ObjectSpec, filters: dict[str, str], request_id: str | None = None) -> list[dict]:
    """Return visible rows matching all filters. Rows with visible_after_calls simulate late postings: hidden for the
    first N lookups of the calling request (X-Request-ID), or of all callers when no request id is sent."""
    table = _tables[spec.table]
    stmt = select(table)
    for key, value in filters.items():
        stmt = stmt.where(table.c[key] == str(value))
    out = []
    with _lock, get_source_engine().begin() as conn:
        for row in conn.execute(stmt).mappings().all():
            conn.execute(update(table).where(table.c._row_id == row["_row_id"]).values(_call_count=(row["_call_count"] or 0) + 1))
            delay = int(row.get("visible_after_calls") or 0) if "visible_after_calls" in row else 0
            seen = row["_call_count"] or 0
            if delay and request_id:
                key = ((late_posting_calls.c.table_name == spec.table) & (late_posting_calls.c.row_id == row["_row_id"])
                       & (late_posting_calls.c.request_id == request_id))
                prev = conn.execute(select(late_posting_calls.c.call_count).where(key)).scalar()
                seen = prev or 0
                if prev is None:
                    conn.execute(late_posting_calls.insert().values(table_name=spec.table, row_id=row["_row_id"],
                                                                    request_id=request_id, call_count=1))
                else:
                    conn.execute(update(late_posting_calls).where(key).values(call_count=prev + 1))
            if seen < delay:
                continue
            out.append({k: _coerce(v) for k, v in row.items() if not k.startswith("_") and k != "visible_after_calls"})
    return out


def get_by_ref(spec: ObjectSpec, ref: str) -> dict | None:
    table = _tables[spec.table]
    with get_source_engine().connect() as conn:
        row = conn.execute(select(table).where(table.c[spec.ref_field] == ref)).mappings().first()
    if not row:
        return None
    return {k: _coerce(v) for k, v in row.items() if not k.startswith("_") and k != "visible_after_calls"}


def _coerce(value):
    if value is None:
        return None
    try:
        if "." in value:
            return float(value)
        if value.isdigit() and len(value) < 6:
            return int(value)
    except (TypeError, ValueError):
        pass
    return value

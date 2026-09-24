"""Request DB engine/session management."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import EXPECTED_SCHEMAS, Base

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _sqlite_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    settings = get_settings()
    url = url or settings.db_url
    if url.startswith("sqlite:///"):
        from pathlib import Path
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    _engine = _sqlite_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    return _engine  # type: ignore[return-value]


def create_schema() -> None:
    Base.metadata.create_all(get_engine())


def validate_schema() -> None:
    """Fail fast if the configuration/workflow tables drift from the exact agreed schemas."""
    insp = inspect(get_engine())
    problems = []
    for table, expected in EXPECTED_SCHEMAS.items():
        if not insp.has_table(table):
            problems.append(f"missing table {table}")
            continue
        actual = {c["name"] for c in insp.get_columns(table)}
        missing = [c for c in expected if c not in actual]
        if missing:
            problems.append(f"{table} missing columns {missing}")
    if problems:
        raise RuntimeError("Request DB schema validation failed: " + "; ".join(problems))


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    session: Session = _SessionLocal()  # type: ignore[misc]
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as s:
        yield s

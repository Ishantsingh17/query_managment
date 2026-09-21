"""Application state database.

Kept entirely separate from the mock source databases so workflow history is
independent of the simulated enterprise systems (schema doc section 11).

A connection is opened per operation because the workflow runs on background
threads and sqlite3 connections are not shareable across them. WAL mode lets
the API keep reading state while a run is still writing it.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_requests (
    id               TEXT PRIMARY KEY,
    raw_query        TEXT NOT NULL,
    status           TEXT NOT NULL,
    use_case_id      TEXT,
    requirement_name TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parsed_queries (
    id         TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    query_json TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_state (
    request_id   TEXT PRIMARY KEY,
    current_step TEXT NOT NULL,
    state_json   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_attempts (
    id                       TEXT PRIMARY KEY,
    request_id               TEXT NOT NULL,
    database_id              TEXT NOT NULL,
    search_parameters_json   TEXT NOT NULL,
    requested_evidence_json  TEXT NOT NULL,
    result_count             INTEGER NOT NULL,
    status                   TEXT NOT NULL,
    error_message            TEXT,
    pass_number              INTEGER NOT NULL DEFAULT 1,
    started_at               TEXT NOT NULL,
    completed_at             TEXT
);

CREATE TABLE IF NOT EXISTS retrieved_evidence (
    id                 TEXT PRIMARY KEY,
    request_id         TEXT NOT NULL,
    document_id        TEXT NOT NULL,
    document_type      TEXT NOT NULL,
    identifier         TEXT,
    source_database_id TEXT NOT NULL,
    source_file_path   TEXT,
    staged_file_path   TEXT,
    match_status       TEXT NOT NULL,
    metadata_json      TEXT,
    pass_number        INTEGER NOT NULL DEFAULT 1,
    retrieved_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_results (
    id                     TEXT PRIMARY KEY,
    request_id             TEXT NOT NULL,
    validation_status      TEXT NOT NULL,
    checks_json            TEXT NOT NULL,
    missing_evidence_json  TEXT,
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id               TEXT PRIMARY KEY,
    request_id       TEXT NOT NULL,
    reviewer_action  TEXT NOT NULL,
    reviewer_comment TEXT,
    reviewer_name    TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_packages (
    id           TEXT PRIMARY KEY,
    request_id   TEXT NOT NULL,
    package_path TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Monotonic request numbering so ids stay stable and human-readable.
CREATE TABLE IF NOT EXISTS id_counter (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_request   ON retrieval_attempts(request_id);
CREATE INDEX IF NOT EXISTS idx_evidence_request   ON retrieved_evidence(request_id);
CREATE INDEX IF NOT EXISTS idx_validation_request ON validation_results(request_id);
CREATE INDEX IF NOT EXISTS idx_parsed_request     ON parsed_queries(request_id);
CREATE INDEX IF NOT EXISTS idx_reviews_request    ON reviews(request_id);
CREATE INDEX IF NOT EXISTS idx_packages_request   ON audit_packages(request_id);
CREATE INDEX IF NOT EXISTS idx_requests_created   ON audit_requests(created_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    settings = get_settings()
    settings.app_state_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.app_state_db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    """Create the schema and seed the request counter. Safe to re-run."""
    settings = get_settings()
    with transaction() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO id_counter (name, value) VALUES ('audit_request', ?)",
            (settings.request_id_seed,),
        )

"""MCP server exposing database search and document retrieval as tools.

This module is the ONLY place that opens a connection to a mock source
database. Agents reach the data exclusively by calling these tools, which is
what keeps database specifics out of agent and prompt logic (TRD section 3).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.catalog.loader import get_database
from app.config import get_settings
from app.mcp_layer.matching import harvest_identifiers, normalize, row_matches

SERVER_NAME = "audit-evidence"

# Columns returned in a normalized match.
_MATCH_FIELDS = (
    "document_type", "vendor_id", "vendor_name", "invoice_number",
    "po_number", "grn_number", "ses_number", "account_number", "sob",
    "nac_code", "period", "report_type", "file_path", "content_summary",
)


def _error(database_id: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "database_id": database_id,
        "status": "ERROR",
        "error_code": code,
        "error_message": message,
        **extra,
    }


def _connect(database_id: str) -> tuple[sqlite3.Connection | None, str | None]:
    """Open a source database read-only. Returns (connection, error)."""
    spec = get_database(database_id)
    if spec is None:
        return None, f"Database {database_id} is not present in the registry."

    path: Path = spec.resolved_path(get_settings().data_root)
    if not path.exists():
        # Surfaces as DATABASE_UNAVAILABLE; the workflow continues elsewhere.
        return None, f"Database file for {database_id} was not found at {spec.path}."

    try:
        # Read-only URI so a search can never mutate a source system.
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn, None
    except sqlite3.Error as exc:
        return None, f"Database {database_id} could not be opened: {exc}"


def _identifier_for(row: dict) -> str:
    """The value shown in the UI's Identifier column."""
    metadata = row.get("metadata_json")
    if metadata:
        try:
            parsed = json.loads(metadata)
            if parsed.get("identifier"):
                return str(parsed["identifier"])
        except (ValueError, TypeError):
            pass
    for key in ("invoice_number", "po_number", "grn_number", "ses_number"):
        if row.get(key):
            return str(row[key])
    return str(row.get("id", ""))


def _normalize_match(row: dict, database_id: str, matched_on: list[str]) -> dict[str, Any]:
    match: dict[str, Any] = {
        "document_id": row.get("id"),
        "identifier": _identifier_for(row),
        "source_database_id": database_id,
        "matched_on": matched_on,
    }
    for field in _MATCH_FIELDS:
        match[field] = row.get(field)
    if row.get("metadata_json"):
        try:
            match["metadata"] = json.loads(row["metadata_json"])
        except (ValueError, TypeError):
            match["metadata"] = None
    return match


# --- tool implementations -------------------------------------------------
# Kept at module level so tools can reuse each other without depending on
# decorator wrappers.


def search_impl(
    database_id: str,
    required_evidence: list[str],
    search_parameters: dict[str, Any],
) -> dict[str, Any]:
    conn, error = _connect(database_id)
    if conn is None:
        return _error(
            database_id,
            "DATABASE_UNAVAILABLE",
            error or "Unknown error",
            matches=[],
            transaction_matches=[],
            discovered_identifiers={},
        )

    context = {k: v for k, v in (search_parameters or {}).items() if v not in (None, "")}
    matches: list[dict[str, Any]] = []
    transaction_matches: list[dict[str, Any]] = []
    discovered: dict[str, str] = {}

    try:
        for raw in conn.execute("SELECT * FROM documents"):
            row = dict(raw)
            matched, matched_on = row_matches(row, list(required_evidence or []), context)
            if matched:
                matches.append(_normalize_match(row, database_id, matched_on))
                discovered.update(harvest_identifiers(row))

        # Transactions corroborate the documents and can reveal further
        # identifiers. They are never returned as evidence themselves.
        for raw in conn.execute("SELECT * FROM transactions"):
            row = dict(raw)
            matched, matched_on = row_matches(row, [], context)
            if matched:
                transaction_matches.append(
                    {
                        "transaction_id": row.get("id"),
                        "transaction_type": row.get("transaction_type"),
                        "amount": row.get("amount"),
                        "currency": row.get("currency"),
                        "period": row.get("period"),
                        "matched_on": matched_on,
                    }
                )
                discovered.update(harvest_identifiers(row))
    except sqlite3.Error as exc:
        return _error(
            database_id,
            "RETRIEVAL_ERROR",
            f"Search of {database_id} failed: {exc}",
            matches=[],
            transaction_matches=[],
            discovered_identifiers={},
        )
    finally:
        conn.close()

    return {
        "database_id": database_id,
        "status": "SUCCESS",
        "error_code": None,
        "error_message": None,
        "matches": matches,
        "transaction_matches": transaction_matches,
        "discovered_identifiers": discovered,
    }


def _passes_filters(row: dict, filters: dict[str, Any] | None) -> bool:
    """Exact, case-insensitive match on every supplied filter column."""
    for column, wanted in (filters or {}).items():
        if wanted in (None, ""):
            continue
        actual = row.get(column)
        if actual in (None, ""):
            return False
        if normalize(actual) != normalize(wanted):
            return False
    return True


# Columns returned for a transaction row.
_TXN_FIELDS = (
    "transaction_type", "vendor_id", "vendor_name", "invoice_number",
    "po_number", "grn_number", "ses_number", "account_number", "sob",
    "nac_code", "amount", "currency", "period", "report_type",
)


def fetch_transactions_impl(
    database_id: str,
    search_parameters: dict[str, Any],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the full transaction rows matching a search context.

    Used to compile tabular evidence (the Excel extract). The same matching
    rules as document search apply, so a request scoped to one SOB and NAC
    range cannot pick up another's lines.

    `filters` is an additional exact-match layer applied on top, for columns
    the shared matcher deliberately ignores. report_type is the case in point:
    a request for an AP cost drill still REQUIRES the AP, AR and Others
    reports as documents, so the matcher must not filter on report_type - but
    the transaction listing behind an AP request should contain AP lines only.
    A row whose value is NULL is excluded, because it cannot be positively
    attributed to the requested type.
    """
    conn, error = _connect(database_id)
    if conn is None:
        return _error(
            database_id, "DATABASE_UNAVAILABLE", error or "Unknown error", rows=[]
        )

    context = {k: v for k, v in (search_parameters or {}).items() if v not in (None, "")}
    rows: list[dict[str, Any]] = []
    try:
        for raw in conn.execute("SELECT * FROM transactions"):
            row = dict(raw)
            matched, matched_on = row_matches(row, [], context)
            if not matched:
                continue
            if not _passes_filters(row, filters):
                continue
            item: dict[str, Any] = {
                "transaction_id": row.get("id"),
                "source_database_id": database_id,
                "matched_on": matched_on,
            }
            for field in _TXN_FIELDS:
                item[field] = row.get(field)
            if row.get("attributes_json"):
                try:
                    item["attributes"] = json.loads(row["attributes_json"])
                except (ValueError, TypeError):
                    item["attributes"] = {}
            else:
                item["attributes"] = {}
            rows.append(item)
    except sqlite3.Error as exc:
        return _error(database_id, "RETRIEVAL_ERROR", str(exc), rows=[])
    finally:
        conn.close()

    return {
        "database_id": database_id,
        "status": "SUCCESS",
        "error_code": None,
        "error_message": None,
        "rows": rows,
    }


def metadata_impl(database_id: str, document_id: str) -> dict[str, Any]:
    conn, error = _connect(database_id)
    if conn is None:
        return _error(database_id, "DATABASE_UNAVAILABLE", error or "Unknown error", document=None)
    try:
        raw = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    except sqlite3.Error as exc:
        return _error(database_id, "RETRIEVAL_ERROR", str(exc), document=None)
    finally:
        conn.close()

    if raw is None:
        return _error(
            database_id,
            "DOCUMENT_NOT_FOUND",
            f"Document {document_id} was not found in {database_id}.",
            document=None,
        )
    return {
        "database_id": database_id,
        "status": "SUCCESS",
        "error_code": None,
        "error_message": None,
        "document": _normalize_match(dict(raw), database_id, []),
    }


def retrieve_impl(database_id: str, document_id: str) -> dict[str, Any]:
    result = metadata_impl(database_id, document_id)
    if result["status"] != "SUCCESS":
        return {**result, "file_path": None, "absolute_path": None, "exists": False}

    document = result["document"]
    relative = document.get("file_path")
    if not relative:
        return _error(
            database_id,
            "DOCUMENT_NOT_FOUND",
            f"Document {document_id} has no file associated with it.",
            document=document,
            file_path=None,
            absolute_path=None,
            exists=False,
        )

    absolute = (get_settings().data_root / relative).resolve()
    exists = absolute.exists()
    return {
        "database_id": database_id,
        "status": "SUCCESS" if exists else "ERROR",
        "error_code": None if exists else "DOCUMENT_NOT_FOUND",
        "error_message": None if exists else f"File missing on disk: {relative}",
        "document": document,
        "file_path": relative,
        "absolute_path": str(absolute),
        "exists": exists,
        "size_bytes": absolute.stat().st_size if exists else 0,
    }


def build_server() -> FastMCP:
    server = FastMCP(SERVER_NAME)

    @server.tool()
    def search_sqlite_database(
        database_id: str,
        required_evidence: list[str],
        search_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Search one source database for the requested evidence types.

        Returns a normalized envelope of matches plus any strong identifiers
        discovered, which the caller can fold into later searches.
        """
        return search_impl(database_id, required_evidence, search_parameters)

    @server.tool()
    def fetch_transactions(
        database_id: str,
        search_parameters: dict[str, Any],
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return transaction rows matching the search context.

        Backs tabular evidence such as a GL transaction listing, which is
        compiled from row-level data rather than retrieved as a document.
        `filters` narrows further on exact column values.
        """
        return fetch_transactions_impl(database_id, search_parameters, filters)

    @server.tool()
    def get_document_metadata(database_id: str, document_id: str) -> dict[str, Any]:
        """Fetch the stored metadata for a single document."""
        return metadata_impl(database_id, document_id)

    @server.tool()
    def retrieve_document(database_id: str, document_id: str) -> dict[str, Any]:
        """Resolve a document's file on disk so the caller can stage a copy.

        Returns the absolute source path; the original file is never modified.
        """
        return retrieve_impl(database_id, document_id)

    return server


# Module-level instance reused by the client wrapper.
mcp_server = build_server()

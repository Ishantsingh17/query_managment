"""Repository functions over the application state tables.

Every read the API performs and every write the workflow makes goes through
here, so app_state.sqlite stays the single authoritative record of a request.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.config import get_settings
from app.services.db import transaction, utc_now

# --- controlled values ----------------------------------------------------
STATUS_RECEIVED = "RECEIVED"
STATUS_UNDERSTANDING = "UNDERSTANDING"
STATUS_PLANNING = "PLANNING"
STATUS_RETRIEVING = "RETRIEVING"
STATUS_VALIDATING = "VALIDATING"
STATUS_INCOMPLETE = "INCOMPLETE"
# The request was understood, but the use case's mandatory inputs were not all
# supplied. Retrieval is deliberately NOT attempted: searching a real source
# system on a partial key set returns confidently wrong evidence rather than
# nothing. The auditor is asked for the missing values and the run resumes.
STATUS_NEEDS_INPUT = "NEEDS_INPUT"
STATUS_READY_FOR_REVIEW = "READY_FOR_REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_ERROR = "ERROR"
STATUS_UNSUPPORTED = "UNSUPPORTED"

ACTIVE_STATUSES = {
    STATUS_RECEIVED,
    STATUS_UNDERSTANDING,
    STATUS_PLANNING,
    STATUS_RETRIEVING,
    STATUS_VALIDATING,
}
TERMINAL_STATUSES = {
    STATUS_READY_FOR_REVIEW,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_ERROR,
    STATUS_UNSUPPORTED,
    STATUS_INCOMPLETE,
    # Waiting on the auditor, so polling should stop until they answer.
    STATUS_NEEDS_INPUT,
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# --- audit_requests -------------------------------------------------------


def next_request_id() -> str:
    """Allocate the next human-readable request id (AUD-00124, ...)."""
    settings = get_settings()
    with transaction() as conn:
        conn.execute(
            "UPDATE id_counter SET value = value + 1 WHERE name = 'audit_request'"
        )
        row = conn.execute(
            "SELECT value FROM id_counter WHERE name = 'audit_request'"
        ).fetchone()
    return f"{settings.request_id_prefix}{row['value']:05d}"


def create_request(raw_query: str) -> dict[str, Any]:
    request_id = next_request_id()
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO audit_requests (id, raw_query, status, use_case_id,"
            " requirement_name, created_at, updated_at)"
            " VALUES (?, ?, ?, NULL, NULL, ?, ?)",
            (request_id, raw_query, STATUS_RECEIVED, now, now),
        )
    return {
        "id": request_id,
        "raw_query": raw_query,
        "status": STATUS_RECEIVED,
        "use_case_id": None,
        "requirement_name": None,
        "created_at": now,
        "updated_at": now,
    }


def get_request(request_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM audit_requests WHERE id = ?", (request_id,)
        ).fetchone()
    return dict(row) if row else None


def list_requests(limit: int = 100) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_requests ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_request(
    request_id: str,
    *,
    status: str | None = None,
    use_case_id: str | None = None,
    requirement_name: str | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if use_case_id is not None:
        fields.append("use_case_id = ?")
        values.append(use_case_id)
    if requirement_name is not None:
        fields.append("requirement_name = ?")
        values.append(requirement_name)
    if not fields:
        return
    fields.append("updated_at = ?")
    values.extend([utc_now(), request_id])
    with transaction() as conn:
        conn.execute(
            f"UPDATE audit_requests SET {', '.join(fields)} WHERE id = ?", values
        )


# --- parsed_queries -------------------------------------------------------


def save_parsed_query(request_id: str, query: dict, confidence: float | None) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parsed_queries (id, request_id, query_json, confidence, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (_new_id(), request_id, json.dumps(query), confidence, utc_now()),
        )


def get_parsed_query(request_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM parsed_queries WHERE request_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (request_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "query": _loads(row["query_json"], {}),
        "confidence": row["confidence"],
        "created_at": row["created_at"],
    }


# --- workflow_state -------------------------------------------------------


def save_workflow_state(request_id: str, current_step: str, state: dict) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO workflow_state (request_id, current_step, state_json, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(request_id) DO UPDATE SET"
            " current_step = excluded.current_step,"
            " state_json = excluded.state_json,"
            " updated_at = excluded.updated_at",
            (request_id, current_step, json.dumps(state, default=str), utc_now()),
        )


def get_workflow_state(request_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM workflow_state WHERE request_id = ?", (request_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "current_step": row["current_step"],
        "state": _loads(row["state_json"], {}),
        "updated_at": row["updated_at"],
    }


# --- retrieval_attempts ---------------------------------------------------


def start_retrieval_attempt(
    request_id: str,
    database_id: str,
    search_parameters: dict,
    requested_evidence: list[str],
    pass_number: int,
) -> str:
    attempt_id = _new_id()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO retrieval_attempts (id, request_id, database_id,"
            " search_parameters_json, requested_evidence_json, result_count, status,"
            " error_message, pass_number, started_at, completed_at)"
            " VALUES (?, ?, ?, ?, ?, 0, 'SEARCHING', NULL, ?, ?, NULL)",
            (
                attempt_id,
                request_id,
                database_id,
                json.dumps(search_parameters),
                json.dumps(requested_evidence),
                pass_number,
                utc_now(),
            ),
        )
    return attempt_id


def complete_retrieval_attempt(
    attempt_id: str, result_count: int, status: str, error_message: str | None = None
) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE retrieval_attempts SET result_count = ?, status = ?,"
            " error_message = ?, completed_at = ? WHERE id = ?",
            (result_count, status, error_message, utc_now(), attempt_id),
        )


def list_retrieval_attempts(request_id: str) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM retrieval_attempts WHERE request_id = ?"
            " ORDER BY pass_number, started_at, rowid",
            (request_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["search_parameters"] = _loads(row["search_parameters_json"], {})
        item["requested_evidence"] = _loads(row["requested_evidence_json"], [])
        result.append(item)
    return result


# --- retrieved_evidence ---------------------------------------------------


def add_retrieved_evidence(
    request_id: str,
    *,
    document_id: str,
    document_type: str,
    identifier: str | None,
    source_database_id: str,
    source_file_path: str | None,
    staged_file_path: str | None,
    match_status: str,
    metadata: dict | None,
    pass_number: int,
) -> str:
    evidence_id = _new_id()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO retrieved_evidence (id, request_id, document_id, document_type,"
            " identifier, source_database_id, source_file_path, staged_file_path,"
            " match_status, metadata_json, pass_number, retrieved_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence_id,
                request_id,
                document_id,
                document_type,
                identifier,
                source_database_id,
                source_file_path,
                staged_file_path,
                match_status,
                json.dumps(metadata) if metadata is not None else None,
                pass_number,
                utc_now(),
            ),
        )
    return evidence_id


def list_retrieved_evidence(request_id: str) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM retrieved_evidence WHERE request_id = ?"
            " ORDER BY pass_number, retrieved_at, rowid",
            (request_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _loads(row["metadata_json"], {})
        result.append(item)
    return result


def get_evidence(request_id: str, evidence_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM retrieved_evidence WHERE request_id = ? AND id = ?",
            (request_id, evidence_id),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _loads(row["metadata_json"], {})
    return item


def set_evidence_match_status(evidence_id: str, match_status: str) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE retrieved_evidence SET match_status = ? WHERE id = ?",
            (match_status, evidence_id),
        )


# --- validation_results ---------------------------------------------------


def save_validation_result(
    request_id: str, validation_status: str, checks: list[dict], missing_evidence: list[str]
) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO validation_results (id, request_id, validation_status,"
            " checks_json, missing_evidence_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                _new_id(),
                request_id,
                validation_status,
                json.dumps(checks),
                json.dumps(missing_evidence),
                utc_now(),
            ),
        )


def latest_validation(request_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM validation_results WHERE request_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (request_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "validation_status": row["validation_status"],
        "checks": _loads(row["checks_json"], []),
        "missing_evidence": _loads(row["missing_evidence_json"], []),
        "created_at": row["created_at"],
    }


# --- reviews --------------------------------------------------------------


def add_review(
    request_id: str, action: str, comment: str | None, reviewer_name: str | None
) -> dict[str, Any]:
    now = utc_now()
    review_id = _new_id()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO reviews (id, request_id, reviewer_action, reviewer_comment,"
            " reviewer_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, request_id, action, comment, reviewer_name, now),
        )
    return {
        "id": review_id,
        "request_id": request_id,
        "reviewer_action": action,
        "reviewer_comment": comment,
        "reviewer_name": reviewer_name,
        "created_at": now,
    }


def list_reviews(request_id: str) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE request_id = ? ORDER BY created_at, rowid",
            (request_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def latest_review(request_id: str) -> dict[str, Any] | None:
    reviews = list_reviews(request_id)
    return reviews[-1] if reviews else None


# --- audit_packages -------------------------------------------------------


def save_package(request_id: str, package_path: str, summary: dict) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM audit_packages WHERE request_id = ?", (request_id,))
        conn.execute(
            "INSERT INTO audit_packages (id, request_id, package_path, summary_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (_new_id(), request_id, package_path, json.dumps(summary, default=str), utc_now()),
        )


def get_package(request_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM audit_packages WHERE request_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (request_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "package_path": row["package_path"],
        "summary": _loads(row["summary_json"], {}),
        "created_at": row["created_at"],
    }

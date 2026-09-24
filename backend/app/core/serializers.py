"""Business-friendly views of DB rows shared by the API and package builders."""
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.labels import EVIDENCE_ICONS, EVIDENCE_SHORT, STATUS_LABELS, evidence_label, query_type_label
from app.db.models import EvidenceItem, RequestEvent, RequestRecord

STEPS = ["Submitted", "Processing", "Validation", "Review", "Approval", "Final Response"]
_STEP_INDEX = {  # index of the current (in-progress) step; len(STEPS) = all done
    "REQUEST_CREATED": 1, "PROCESSING": 1, "VALIDATION_PENDING": 2, "REWORK_REQUIRED": 2, "REJECTED": 2,
    "REVIEW_READY": 3, "SME_REVIEW": 4, "APPROVED": 5, "FINAL_RESPONSE_READY": 5, "NOTIFIED": 6, "COMPLETED": 6,
}
SLA_DAYS = 7


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime | None) -> str | None:
    dt = as_utc(dt)
    return dt.isoformat() if dt else None


def loads(s: str | None) -> dict[str, Any]:
    try:
        return json.loads(s) if s else {}
    except ValueError:
        return {}


def evidence_view(item: EvidenceItem) -> dict[str, Any]:
    payload = loads(item.normalized_payload_json)
    meta = payload.get("metadata", {})
    return {
        "evidence_id": item.evidence_id,
        "evidence_type": item.evidence_type,
        "label": evidence_label(item.evidence_type),
        "short_label": EVIDENCE_SHORT.get(item.evidence_type, item.evidence_type),
        "icon": EVIDENCE_ICONS.get(item.evidence_type, "file"),
        "source_system": item.source_system,
        "source_reference": item.source_reference,
        "retrieval_method": item.retrieval_method,
        "payload_type": item.payload_type,
        "status": item.validation_status,
        "reason": item.validation_reason,
        "description": meta.get("description"),
        "notes": meta.get("notes", []),
        "corroboration": meta.get("corroboration", []),
        "uploaded_by": meta.get("uploaded_by"),
        "justification": meta.get("justification"),
        "has_file": bool(item.file_path) or item.validation_status in ("AVAILABLE", "MANUALLY_UPLOADED"),
        "is_approved": item.is_approved,
        "created_at": iso(item.created_at),
    }


def evidence_counts(items: list[EvidenceItem], required: list[str]) -> dict[str, int]:
    latest = {i.evidence_type: i.validation_status for i in items}
    statuses = [latest.get(et, "PENDING") for et in required]  # not yet retrieved != missing
    c = {s: statuses.count(s) for s in ("AVAILABLE", "MISSING", "MANUALLY_UPLOADED", "NOT_REQUIRED")}
    total = len(required)
    done = c["AVAILABLE"] + c["MANUALLY_UPLOADED"] + c["NOT_REQUIRED"]
    return {"required": total, "available": c["AVAILABLE"], "missing": c["MISSING"], "manual": c["MANUALLY_UPLOADED"],
            "not_required": c["NOT_REQUIRED"], "completeness_pct": round(100 * done / total) if total else 0}


def request_summary(r: RequestRecord, counts: dict[str, int] | None = None, missing_labels: list[str] | None = None) -> dict[str, Any]:
    created = as_utc(r.created_at)
    return {
        "request_id": r.request_id,
        "query_type": r.query_type,
        "query_type_label": query_type_label(r.query_type) if r.query_type else "Classifying…",
        "status": r.status,
        "status_label": STATUS_LABELS.get(r.status, r.status),
        "validation_status": r.validation_status,
        "approval_status": r.approval_status,
        "notification_status": r.notification_status,
        "created_at": iso(created),
        "updated_at": iso(r.updated_at),
        "due_at": iso(created + timedelta(days=SLA_DAYS)) if created else None,
        "completeness_pct": (counts or {}).get("completeness_pct", 0),
        "counts": counts,
        "missing_evidence": missing_labels or [],
        "original_query": r.original_query,
    }


def stepper(status: str) -> list[dict[str, Any]]:
    current = _STEP_INDEX.get(status, 0)
    return [{"label": s, "state": "done" if i < current else "current" if i == current else "todo"}
            for i, s in enumerate(STEPS)]


def event_view(e: RequestEvent) -> dict[str, Any]:
    return {"id": e.event_id, "stage": e.stage, "type": e.event_type, "title": e.title, "detail": e.detail,
            "actor_name": e.actor_name, "actor_role": e.actor_role, "created_at": iso(e.created_at)}

"""Request DB persistence helpers used by the Orchestrator (the only writer of workflow state)."""
import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.models import CanonicalEvidence
from app.db.models import EvidenceItem, RequestEvent, RequestRecord, User

log = logging.getLogger(__name__)

# Allowed transitions (Backend Schema §6)
TRANSITIONS: dict[str, set[str]] = {
    "REQUEST_CREATED": {"PROCESSING", "REWORK_REQUIRED"},
    "PROCESSING": {"VALIDATION_PENDING", "REWORK_REQUIRED"},
    "VALIDATION_PENDING": {"REVIEW_READY", "REWORK_REQUIRED", "PROCESSING", "VALIDATION_PENDING"},
    "REWORK_REQUIRED": {"PROCESSING", "VALIDATION_PENDING", "REWORK_REQUIRED", "REVIEW_READY"},
    "REVIEW_READY": {"SME_REVIEW", "APPROVED", "REJECTED"},
    "SME_REVIEW": {"APPROVED", "REJECTED"},
    "REJECTED": {"REWORK_REQUIRED"},
    "APPROVED": {"FINAL_RESPONSE_READY"},
    "FINAL_RESPONSE_READY": {"NOTIFIED"},
    "NOTIFIED": {"COMPLETED"},
    "COMPLETED": set(),
}


class InvalidTransition(RuntimeError):
    pass


def get_request(session: Session, request_id: str, *, lock: bool = False) -> RequestRecord:
    r = session.get(RequestRecord, request_id)
    if r is None:
        raise NotFoundError(f"Request {request_id} was not found.")
    return r


def set_status(session: Session, r: RequestRecord, new: str) -> None:
    if new != r.status and new not in TRANSITIONS.get(r.status, set()):
        raise InvalidTransition(f"{r.request_id}: {r.status} -> {new} not allowed")
    log.info("status change %s -> %s", r.status, new, extra={"request_id": r.request_id})
    r.status = new


def add_event(session: Session, request_id: str, stage: str, event_type: str, title: str,
              detail: str | None = None, actor: User | None = None, actor_name: str | None = None,
              actor_role: str | None = None) -> None:
    session.add(RequestEvent(
        request_id=request_id, stage=stage, event_type=event_type, title=title, detail=detail,
        actor_name=actor.full_name if actor else actor_name,
        actor_role=({"AUDITOR": "Auditor", "VALIDATOR": "Validator", "SME": "SME"}.get(actor.role) if actor else actor_role),
    ))


def items_for(session: Session, request_id: str) -> list[EvidenceItem]:
    return list(session.scalars(select(EvidenceItem).where(EvidenceItem.request_id == request_id)
                                .order_by(EvidenceItem.created_at)))


def replace_item(session: Session, request_id: str, evidence_type: str, item: EvidenceItem) -> EvidenceItem:
    """One current evidence row per (request, evidence type); history lives in staging + events."""
    session.execute(delete(EvidenceItem).where(EvidenceItem.request_id == request_id,
                                               EvidenceItem.evidence_type == evidence_type))
    session.add(item)
    return item


def item_from_canonical(ev: CanonicalEvidence) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=ev.evidence_id, request_id=ev.request_id, evidence_type=ev.evidence_type,
        source_system=ev.source_system, source_reference=ev.source_reference, retrieval_method="API",
        payload_type=ev.payload_type, file_path=ev.original_file_path,
        normalized_payload_json=json.dumps(ev.model_dump(mode="json"), default=str),
        validation_status="AVAILABLE", validation_reason=None, is_approved=False, created_at=ev.retrieved_at,
    )


def patch_metadata(item: EvidenceItem, **meta: Any) -> None:
    data = json.loads(item.normalized_payload_json) if item.normalized_payload_json else {}
    data.setdefault("metadata", {}).update(meta)
    item.normalized_payload_json = json.dumps(data, default=str)


def users_with_role(session: Session, role: str) -> list[User]:
    return list(session.scalars(select(User).where(User.role == role)))

"""Orchestrator service: request lifecycle and human-workflow actions.

Workflow execution (graph) runs in the background; human actions (upload, accept, continue,
approve, reject) are synchronous state transitions validated against the state machine.
"""
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError
from app.core.labels import evidence_label, query_type_label
from app.core.serializers import iso
from app.db.models import ApprovalAction, EvidenceItem, ManualUpload, RequestRecord, User
from app.evidence import staging
from app.evidence.normalization import new_evidence_id
from app.notifications.service import notify
from app.orchestrator import persistence as db
from app.packages import builder
from app.registry.resolution import resolve_requirements
from app.validation.engine import validate_completeness

HUMAN_ACTION_STATES = {"VALIDATION_PENDING", "REWORK_REQUIRED"}
DECISION_STATES = {"REVIEW_READY", "SME_REVIEW"}
ALLOWED_UPLOAD_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".csv", ".xlsx", ".xls"}
MAX_UPLOAD_MB = 25
DUPLICATE_WINDOW = timedelta(minutes=10)
# In-app destinations used by email links (always reached through /login?next=...)
VALIDATOR_PATH = "/validation/requests/{rid}"
SME_PATH = "/approvals/requests/{rid}"
AUDITOR_PATH = "/requests/{rid}/package"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def next_request_id(session: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"AUD-{year}-"
    last = session.scalar(select(func.max(RequestRecord.request_id)).where(RequestRecord.request_id.like(f"{prefix}%")))
    seq = int(last.removeprefix(prefix)) + 1 if last else 1001
    return f"{prefix}{seq}"


# ---- Intake -------------------------------------------------------------------------------------

def create_request(session: Session, auditor: User, query: str, identifiers: dict, query_type: str | None,
                   precomputed: dict | None = None) -> RequestRecord:
    identifiers = {k: str(v).strip() for k, v in identifiers.items() if v not in (None, "")}
    since = datetime.now(timezone.utc) - DUPLICATE_WINDOW
    recent = session.scalars(select(RequestRecord).where(RequestRecord.auditor_id == auditor.user_id,
                                                         RequestRecord.created_at >= since))
    for r in recent:
        intake = json.loads(r.structured_query_json or "{}")
        if _norm(r.original_query) == _norm(query) and intake.get("known_identifiers", {}) == identifiers \
                and r.status not in ("COMPLETED",):
            raise ConflictError(f"An identical request ({r.request_id}) was submitted moments ago and is already in progress.",
                                code="duplicate_request")

    r = RequestRecord(request_id=next_request_id(session), auditor_id=auditor.user_id, original_query=query.strip(),
                      structured_query_json=json.dumps({"known_identifiers": identifiers, "user_selected_query_type": query_type,
                                                        "precomputed": precomputed}),
                      query_type=query_type, status="REQUEST_CREATED", validation_status=None, approval_status="PENDING",
                      notification_status=None)
    session.add(r)
    session.flush()
    db.add_event(session, r.request_id, "Submitted", "submit", f"Request submitted by {auditor.full_name}",
                 "Natural-language request accepted.", actor=auditor)
    return r


# ---- Validation / human workflow ----------------------------------------------------------------

def _require_state(r: RequestRecord, allowed: set[str], action: str) -> None:
    if r.status not in allowed:
        raise ConflictError(f"{action} is not available while the request is {r.status.replace('_', ' ').title()}.",
                            code="invalid_state")


def _required_types(session: Session, r: RequestRecord) -> list[str]:
    return [q.evidence_type for q in resolve_requirements(session, r.query_type)] if r.query_type else []


def _check_evidence_type(session: Session, r: RequestRecord, evidence_type: str) -> None:
    if evidence_type not in _required_types(session, r):
        raise AppError(f"{evidence_type} is not a required evidence type for this request.", code="invalid_evidence_type")


def request_retry(session: Session, rid: str, actor: User, evidence_types: list[str] | None) -> list[str]:
    r = db.get_request(session, rid)
    _require_state(r, HUMAN_ACTION_STATES, "Retry")
    items = {i.evidence_type: i for i in db.items_for(session, rid)}
    required = _required_types(session, r)
    if not required:
        raise ConflictError("This request has no resolved query type; please resubmit it with a Query type.", code="unclassified")
    targets = evidence_types or [et for et in required if items.get(et) is None or items[et].validation_status == "MISSING"]
    for et in targets:
        _check_evidence_type(session, r, et)
    if not targets:
        raise ConflictError("Nothing to retry — all required evidence is available.", code="nothing_to_retry")
    db.set_status(session, r, "PROCESSING")
    db.add_event(session, rid, "Validation", "progress", f"Retry / rework started by {actor.full_name}",
                 "Re-running retrieval for " + ", ".join(evidence_label(t) for t in targets) + ".", actor=actor)
    return targets


def manual_upload(session: Session, rid: str, actor: User, evidence_type: str, filename: str, content: bytes,
                  notes: str | None, source_reference: str | None) -> EvidenceItem:
    r = db.get_request(session, rid)
    _require_state(r, HUMAN_ACTION_STATES, "Manual upload")
    _check_evidence_type(session, r, evidence_type)
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_UPLOAD_EXT:
        raise AppError("Unsupported file type. Upload a PDF, PNG, JPG, CSV or Excel file.", code="unsupported_file")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise AppError(f"File is larger than {MAX_UPLOAD_MB} MB.", code="file_too_large")
    if not content:
        raise AppError("The uploaded file is empty.", code="empty_file")

    path = staging.write_manual_upload(rid, f"{evidence_type}_{filename}", content)
    rel = staging.relative(path)
    previous = next((i for i in db.items_for(session, rid) if i.evidence_type == evidence_type), None)
    source = previous.source_system if previous else None
    size_kb = max(1, len(content) // 1024)
    kind = (mimetypes.guess_type(filename)[0] or "file").split("/")[-1].upper()
    item = EvidenceItem(
        evidence_id=new_evidence_id(), request_id=rid, evidence_type=evidence_type, source_system=source,
        source_reference=source_reference or (previous.source_reference if previous else None) or filename,
        retrieval_method="MANUAL_UPLOAD", payload_type="PDF" if ext == ".pdf" else kind, file_path=rel,
        normalized_payload_json=json.dumps({"metadata": {
            "description": f"{'Signed approval' if 'APPROVAL' in evidence_type else 'Document'} · uploaded by validator · {size_kb} KB",
            "uploaded_by": actor.full_name, "original_filename": filename, "size_kb": size_kb,
            "upload_notes": notes, "sha256": hashlib.sha256(content).hexdigest()}}),
        validation_status="MANUALLY_UPLOADED", validation_reason=None, is_approved=False,
    )
    db.replace_item(session, rid, evidence_type, item)
    session.add(ManualUpload(upload_id=f"UPL-{uuid.uuid4().hex[:10].upper()}", request_id=rid, evidence_type=evidence_type,
                             file_path=rel, uploaded_by=actor.user_id, notes=notes))
    db.set_status(session, r, "VALIDATION_PENDING")
    db.add_event(session, rid, "Validation", "success", f"{evidence_label(evidence_type)} uploaded manually",
                 f"{filename} ({size_kb} KB) staged by {actor.full_name}." + (f" Note: {notes}" if notes else ""), actor=actor)
    return item


def accept_not_required(session: Session, rid: str, actor: User, evidence_type: str, justification: str) -> EvidenceItem:
    r = db.get_request(session, rid)
    _require_state(r, HUMAN_ACTION_STATES, "Accept not required")
    _check_evidence_type(session, r, evidence_type)
    if not justification or len(justification.strip()) < 5:
        raise AppError("A justification is required to accept an item as not required.", code="justification_required")
    item = next((i for i in db.items_for(session, rid) if i.evidence_type == evidence_type), None)
    if item is None:
        item = EvidenceItem(evidence_id=new_evidence_id(), request_id=rid, evidence_type=evidence_type,
                            validation_status="NOT_REQUIRED", is_approved=False)
        session.add(item)
    item.validation_status = "NOT_REQUIRED"
    item.validation_reason = justification.strip()
    db.patch_metadata(item, justification=justification.strip(), accepted_by=actor.full_name)
    db.set_status(session, r, "VALIDATION_PENDING")
    db.add_event(session, rid, "Validation", "info", f"{evidence_label(evidence_type)} accepted as not required",
                 justification.strip(), actor=actor)
    return item


def continue_validation(session: Session, rid: str, actor: User, note: str | None) -> dict:
    """Validator confirms; completeness is re-checked. Complete -> Review Package; else Rework Required."""
    r = db.get_request(session, rid)
    _require_state(r, HUMAN_ACTION_STATES, "Continue")
    result = validate_completeness(rid, _required_types(session, r), db.items_for(session, rid))
    r.validation_status = "COMPLETE" if result.is_complete else "INCOMPLETE"
    if not result.is_complete:
        db.set_status(session, r, "REWORK_REQUIRED")
        missing = ", ".join(evidence_label(e) for e in result.missing_evidence)
        db.add_event(session, rid, "Validation", "warning", "Completeness check: evidence still missing", missing, actor=actor)
        session.commit()  # persist the REWORK_REQUIRED outcome before reporting it
        raise ConflictError(f"Cannot continue — still missing: {missing}. Retry, upload, or accept as not required.",
                            code="incomplete")
    db.add_event(session, rid, "Validation", "success", "Validation finished",
                 note or "All required evidence available or accepted.", actor=actor)
    prepare_review_package(session, rid, validated_by=actor.full_name, note=note, actor=actor)
    return result.model_dump()


def prepare_review_package(session: Session, rid: str, validated_by: str, note: str | None, actor: User | None) -> None:
    """Orchestrator: collect outputs -> Evidence Review Package -> Request DB -> notify SME."""
    r = db.get_request(session, rid)
    items = db.items_for(session, rid)
    result = validate_completeness(rid, _required_types(session, r), items)
    pkg = builder.build_review_package(r, items, result, validated_by, note)
    r.review_package_path = pkg.package_path
    r.validation_status = "COMPLETE"
    r.approval_status = "PENDING"
    db.set_status(session, r, "REVIEW_READY")
    db.add_event(session, rid, "Review", "success", "Review package ready",
                 f"Evidence Review Package v{pkg.version} submitted for SME approval.",
                 actor_name="Validation team" if actor else "Workflow", actor_role="System")
    statuses = [notify(session, rid, "REVIEW_PACKAGE_READY", u, SME_PATH.format(rid=rid), _context(r)).status
                for u in db.users_with_role(session, "SME")]
    r.notification_status = "SME_" + ("FAILED" if "FAILED" in statuses else "NOTIFIED")
    db.add_event(session, rid, "Review", "info", "SME notified", "Email with a sign-in link to the Evidence Review Package.",
                 actor_name="Notification service", actor_role="System")


def _context(r: RequestRecord, **extra) -> dict:
    summary = r.original_query if len(r.original_query) <= 160 else r.original_query[:157] + "…"
    return {"query_type_label": query_type_label(r.query_type), "summary": summary, **extra}


def notify_validators(session: Session, rid: str, missing: list[str], event_type: str = "VALIDATION_REQUIRED",
                      comment: str | None = None) -> None:
    """Missing / unclear evidence -> Request DB -> Notification Service -> Gmail -> Human Validator."""
    r = db.get_request(session, rid)
    statuses = [notify(session, rid, event_type, u, VALIDATOR_PATH.format(rid=rid),
                       _context(r, missing=missing, comment=comment)).status
                for u in db.users_with_role(session, "VALIDATOR")]
    r.notification_status = "VALIDATOR_" + ("FAILED" if "FAILED" in statuses else "NOTIFIED")
    db.add_event(session, rid, "Validation", "info", "Human Validator notified",
                 "Email with a sign-in link to the Validation Portal.", actor_name="Notification service", actor_role="System")


# ---- SME decision -------------------------------------------------------------------------------

def mark_sme_opened(session: Session, rid: str, sme: User) -> None:
    r = db.get_request(session, rid)
    if r.status == "REVIEW_READY":
        db.set_status(session, r, "SME_REVIEW")
        db.add_event(session, rid, "Approval", "progress", "SME review in progress", None, actor=sme)


def approve(session: Session, rid: str, sme: User, comment: str | None) -> None:
    r = db.get_request(session, rid)
    _require_state(r, DECISION_STATES, "Approval")
    session.add(ApprovalAction(approval_id=f"APV-{uuid.uuid4().hex[:10].upper()}", request_id=rid, approver_id=sme.user_id,
                               action="APPROVE", comment=(comment or "").strip() or None))
    for i in db.items_for(session, rid):
        i.is_approved = i.validation_status in builder.APPROVABLE
    r.approval_status = "APPROVED"
    db.set_status(session, r, "APPROVED")
    db.add_event(session, rid, "Approval", "success", f"Package approved by {sme.full_name}", comment, actor=sme)
    # Approval is committed on its own; finalize() runs in a separate transaction so a
    # package-generation failure leaves the request APPROVED and regenerable.
    session.commit()


def reject(session: Session, rid: str, sme: User, comment: str) -> None:
    r = db.get_request(session, rid)
    _require_state(r, DECISION_STATES, "Rejection")
    if not comment or not comment.strip():
        raise AppError("A comment is required to reject this package.", code="comment_required")
    session.add(ApprovalAction(approval_id=f"APV-{uuid.uuid4().hex[:10].upper()}", request_id=rid, approver_id=sme.user_id,
                               action="REJECT", comment=comment.strip()))
    for i in db.items_for(session, rid):
        i.is_approved = False
    r.approval_status = "REJECTED"
    db.set_status(session, r, "REJECTED")
    db.add_event(session, rid, "Approval", "error", f"Package rejected by {sme.full_name}", comment.strip(), actor=sme)
    db.set_status(session, r, "REWORK_REQUIRED")
    r.validation_status = "REWORK"
    db.add_event(session, rid, "Validation", "warning", "Returned to validation as Rework Required",
                 "Rework, re-upload or retry evidence, then continue to resubmit.", actor_name="Workflow", actor_role="System")
    notify_validators(session, rid, [], event_type="REWORK_REQUESTED", comment=comment.strip())


def finalize(session: Session, rid: str) -> None:
    """After SME approval: Final Response Package from approved evidence only -> storage -> notify auditor."""
    r = db.get_request(session, rid)
    _require_state(r, {"APPROVED"}, "Final package generation")
    last = session.scalars(select(ApprovalAction).where(ApprovalAction.request_id == rid, ApprovalAction.action == "APPROVE")
                           .order_by(ApprovalAction.acted_at.desc())).first()
    approver = session.get(User, last.approver_id) if last else None
    approval = {"approver_name": approver.full_name if approver else None, "approver_title": approver.title if approver else None,
                "comment": last.comment if last else None, "acted_at": iso(last.acted_at) if last else None}
    try:
        pkg = builder.build_final_package(r, db.items_for(session, rid), approval)
    except (builder.PackageError, OSError) as exc:
        db.add_event(session, rid, "Final Response", "error", "Final package generation failed",
                     f"{exc}. The package can be regenerated once resolved.", actor_name="Workflow", actor_role="System")
        session.commit()
        raise AppError("The Final Response Package could not be generated. It can be regenerated from the request page.",
                       code="package_failed", status_code=500) from exc
    r.final_response_path = pkg.package_path
    db.set_status(session, r, "FINAL_RESPONSE_READY")
    db.add_event(session, rid, "Final Response", "success", "Final Response Package sealed",
                 f"{len(pkg.approved_evidence)} approved evidence items · checksum {pkg.checksum[:12]}…",
                 actor_name="Workflow", actor_role="System")
    auditor = session.get(User, r.auditor_id)
    ev = notify(session, rid, "FINAL_RESPONSE_READY", auditor, AUDITOR_PATH.format(rid=rid), _context(r))
    r.notification_status = "AUDITOR_" + ("FAILED" if ev.status == "FAILED" else "NOTIFIED")
    db.set_status(session, r, "NOTIFIED")
    db.add_event(session, rid, "Final Response", "info", "Auditor notified",
                 "Email with a sign-in link " + ("failed — the package is available in the app." if ev.status == "FAILED" else "sent."),
                 actor_name="Notification service", actor_role="System")
    db.set_status(session, r, "COMPLETED")
    db.add_event(session, rid, "Final Response", "success", "Request completed", None, actor_name="Workflow", actor_role="System")

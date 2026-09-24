"""Request APIs (Backend Schema §8) plus role-aware queue/list views."""
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from observability import get_observability
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.core.config import get_settings
from app.core.errors import AppError, ForbiddenError
from app.core.labels import EVIDENCE_SHORT, evidence_label, query_type_label
from app.core.serializers import event_view, evidence_counts, evidence_view, iso, loads, request_summary, stepper
from app.db.models import ApprovalAction, RequestEvent, RequestRecord, User
from app.db.session import get_db, session_scope
from app.orchestrator import graph
from app.orchestrator import persistence as db_ops
from app.orchestrator import intake, service
from app.packages import builder
from app.registry.resolution import analyze_parameters, query_type_definitions, resolve_requirements, resolve_source_mappings

router = APIRouter(prefix="/api/requests", tags=["requests"])

ACTIVE_PROCESSING = {"REQUEST_CREATED", "PROCESSING"}
AWAITING = {"VALIDATION_PENDING", "REWORK_REQUIRED", "REVIEW_READY", "SME_REVIEW", "APPROVED", "FINAL_RESPONSE_READY"}
DONE = {"NOTIFIED", "COMPLETED"}
VIEW_STATUSES = {
    "queue": {"VALIDATION_PENDING", "REWORK_REQUIRED", "REVIEW_READY", "PROCESSING"},
    "approvals": {"REVIEW_READY", "SME_REVIEW"},
}


class Identifiers(BaseModel):
    payment_document_number: str | None = None
    invoice_number: str | None = None
    po_number: str | None = None
    vendor_id: str | None = None
    employee_id: str | None = None
    fiscal_year: str | None = None


class AnalyzeBody(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    identifiers: Identifiers = Identifiers()
    date_from: str | None = None
    date_to: str | None = None
    query_type: str | None = None


class CreateBody(AnalyzeBody):
    query: str = Field(min_length=15, max_length=4000)


def _identifiers(body) -> dict:
    ids = body.identifiers.model_dump()
    if getattr(body, "date_from", None):
        ids["period_start"] = body.date_from
    if getattr(body, "date_to", None):
        ids["period_end"] = body.date_to
    return {k: str(v).strip() for k, v in ids.items() if v not in (None, "")}


_STATUS_ERRORS = {
    "WAITING_FOR_PARAMETERS": ("parameters_required", "Some required details are missing."),
    "NEEDS_CLARIFICATION": ("query_type_ambiguous", "Please confirm which Query Type you need."),
    "UNSUPPORTED": ("query_type_unsupported", "This request doesn't match a supported Query Type."),
}


@router.get("/query-types")
def query_types(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"value": qt, "label": d.display_name, "evidence_required": d.evidence_required,
             "automation_behavior": d.automation_behavior} for qt, d in query_type_definitions(db).items()]


@router.post("/analyze")
def analyze(body: AnalyzeBody, db: Session = Depends(get_db), _: User = Depends(require_role("AUDITOR"))):
    """Request Understanding for the conversational intake (no request is created)."""
    with get_observability().workflow("request_analysis", component="request_intake", operation="analyze") as wf:
        understanding = intake.analyze_request(db, body.query, _identifiers(body), body.query_type)
        wf.annotate(retrieval_status=understanding.get("retrieval_status"))
        return intake.public(understanding)


@router.post("", status_code=201)
def create(body: CreateBody, background: BackgroundTasks, db: Session = Depends(get_db),
           user: User = Depends(require_role("AUDITOR"))):
    ids = _identifiers(body)
    obs = get_observability()
    with obs.workflow("request_intake", component="request_intake", operation="create_request") as wf:
        understanding = intake.analyze_request(db, body.query, ids, body.query_type)
        status = understanding["retrieval_status"]
        wf.annotate(retrieval_status=status)
        if status == "READY":
            r = service.create_request(db, user, body.query, ids, understanding["query_type"] if body.query_type else None,
                                       precomputed=understanding["_structured_query"])
            db.commit()
            obs.bind(request_id=r.request_id)  # the intake trace (incl. its LLM call) now correlates to the request
            analysis_trace = understanding.get("_observability_trace_id")
            if analysis_trace and analysis_trace != wf.trace_id:  # understanding reused from an earlier /analyze call
                obs.link_trace(analysis_trace, request_id=r.request_id, reason="reused_cached_analysis")
    if status != "READY":
        code, _ = _STATUS_ERRORS[status]
        raise AppError(understanding["message"], code=code, status_code=422, details=intake.public(understanding))
    background.add_task(graph.run, r.request_id, "full")
    return {"request_id": r.request_id, "status": r.status}


# ---- listing -----------------------------------------------------------------------------------

def _scoped(db: Session, user: User, view: str):
    stmt = select(RequestRecord)
    if view == "completed":
        rejected_ids = select(ApprovalAction.request_id).where(ApprovalAction.action == "REJECT")
        stmt = stmt.where(or_(RequestRecord.status.in_(DONE), RequestRecord.request_id.in_(rejected_ids)))
        if user.role == "AUDITOR":
            stmt = stmt.where(RequestRecord.auditor_id == user.user_id)
        return stmt
    if user.role == "AUDITOR":
        return stmt.where(RequestRecord.auditor_id == user.user_id)
    if user.role == "VALIDATOR":
        return stmt.where(RequestRecord.status.in_(VIEW_STATUSES["queue"])) if view == "queue" else stmt
    if user.role == "SME":
        return stmt.where(RequestRecord.status.in_(VIEW_STATUSES["approvals"])) if view == "approvals" else stmt
    return stmt


def _period_start(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "last_30":
        return now - timedelta(days=30)
    if period == "last_90":
        return now - timedelta(days=90)
    return None


def _row(db: Session, r: RequestRecord) -> dict:
    items = db_ops.items_for(db, r.request_id)
    required = [q.evidence_type for q in resolve_requirements(db, r.query_type)] if r.query_type else []
    counts = evidence_counts(items, required) if required else None
    by_type = {i.evidence_type: i for i in items}
    missing = []
    for et in required:
        i = by_type.get(et)
        if i and i.validation_status == "MISSING":
            short = EVIDENCE_SHORT.get(et, et)
            missing.append(f"{i.source_system} {short}" if i.source_system else short)
    row = request_summary(r, counts, missing)
    del row["original_query"]
    return row


@router.get("")
def list_requests(
    view: Literal["dashboard", "queue", "approvals", "completed", "all"] = "dashboard",
    status: str | None = None, query_type: str | None = None, search: str | None = None,
    period: Literal["all", "this_month", "last_30", "last_90"] = "all",
    missing: Literal["any", "missing", "complete"] = "any",
    approval: Literal["all", "APPROVED", "REJECTED"] = "all",
    sort: Literal["updated", "created"] = "updated",
    page: int = Query(1, ge=1), page_size: int = Query(6, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    stmt = _scoped(db, user, view)
    if status:
        stmt = stmt.where(RequestRecord.status.in_(status.split(",")))
    if query_type:
        stmt = stmt.where(RequestRecord.query_type == query_type)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(RequestRecord.request_id.ilike(like), RequestRecord.original_query.ilike(like),
                              RequestRecord.structured_query_json.ilike(like)))
    start = _period_start(period)
    if start:
        stmt = stmt.where(RequestRecord.created_at >= start)
    if approval != "all":
        stmt = stmt.where(RequestRecord.approval_status == approval)
    stmt = stmt.order_by((RequestRecord.updated_at if sort == "updated" else RequestRecord.created_at).desc())
    rows = [_row(db, r) for r in db.scalars(stmt)]
    if missing == "missing":
        rows = [r for r in rows if r["missing_evidence"]]
    elif missing == "complete":
        rows = [r for r in rows if not r["missing_evidence"]]
    if view == "completed":
        for row in rows:
            _decorate_completed(db, row)
    if view == "approvals":
        for row in rows:
            ev = db.scalar(select(RequestEvent).where(RequestEvent.request_id == row["request_id"],
                                                      RequestEvent.title == "Review package ready")
                           .order_by(RequestEvent.created_at.desc()))
            row["submitted_at"] = iso(ev.created_at) if ev else row["updated_at"]
    total = len(rows)
    start_i = (page - 1) * page_size
    return {"items": rows[start_i:start_i + page_size], "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


def _decorate_completed(db: Session, row: dict) -> None:
    last = db.scalars(select(ApprovalAction).where(ApprovalAction.request_id == row["request_id"])
                      .order_by(ApprovalAction.acted_at.desc())).first()
    row["decision"] = last.action if last else None
    row["decided_at"] = iso(last.acted_at) if last else row["updated_at"]
    row["final_response_ready"] = row["status"] in DONE


@router.get("/export.csv")
def export_register(view: Literal["completed", "dashboard", "queue", "approvals"] = "completed",
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Request ID", "Query Type", "Status", "Approval", "Completeness %", "Created", "Updated"])
    for r in db.scalars(_scoped(db, user, view).order_by(RequestRecord.updated_at.desc())):
        row = _row(db, r)
        w.writerow([r.request_id, row["query_type_label"], row["status_label"], r.approval_status or "",
                    row["completeness_pct"], row["created_at"], row["updated_at"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="audit_request_register.csv"'})


# ---- detail ------------------------------------------------------------------------------------

def _load_for(db: Session, rid: str, user: User) -> RequestRecord:
    r = db_ops.get_request(db, rid)
    if user.role == "AUDITOR" and r.auditor_id != user.user_id:
        raise ForbiddenError("You do not have access to this request.")
    return r


def _actions(r: RequestRecord, user: User) -> list[str]:
    if user.role == "VALIDATOR" and r.status in service.HUMAN_ACTION_STATES:
        return ["retry", "upload", "accept_not_required", "continue"]
    if user.role == "SME" and r.status in service.DECISION_STATES:
        return ["approve", "reject"]
    if r.status == "APPROVED" and user.role in ("SME", "VALIDATOR"):
        return ["finalize"]
    return []


@router.get("/{rid}")
def detail(rid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _load_for(db, rid, user)
    reqs = resolve_requirements(db, r.query_type) if r.query_type else []
    items = {i.evidence_type: i for i in db_ops.items_for(db, rid)}
    evidence = []
    for q in reqs:
        if q.evidence_type in items:
            ev = evidence_view(items[q.evidence_type])
        else:
            ev = {"evidence_id": None, "evidence_type": q.evidence_type, "label": evidence_label(q.evidence_type),
                  "status": "PENDING", "source_system": None, "source_reference": None, "description": None,
                  "icon": "file", "has_file": False}
        ev["requirement_id"] = q.requirement_id
        ev["evidence_description"] = q.evidence_description
        if user.role == "AUDITOR" and not ev.get("is_approved"):
            ev["has_file"] = False  # auditors access approved evidence only
        evidence.append(ev)
    counts = evidence_counts(list(items.values()), [q.evidence_type for q in reqs]) if reqs else None
    events = db.scalars(select(RequestEvent).where(RequestEvent.request_id == rid).order_by(RequestEvent.created_at.desc(),
                                                                                             RequestEvent.event_id.desc()))
    review_pkg = builder.load_package(r.review_package_path) if r.review_package_path else None
    auditor = db.get(User, r.auditor_id)
    decisions = []
    for a in db.scalars(select(ApprovalAction).where(ApprovalAction.request_id == rid).order_by(ApprovalAction.acted_at.desc())):
        approver = db.get(User, a.approver_id)
        decisions.append({"action": a.action, "comment": a.comment, "acted_at": iso(a.acted_at),
                          "approver_name": approver.full_name if approver else None,
                          "approver_title": approver.title if approver else None,
                          "approver_initials": "".join(p[0] for p in approver.full_name.split()[:2]) if approver else None})
    sq = loads(r.structured_query_json)
    params = {k: v for k, v in sq.get("parameters", sq.get("known_identifiers", {})).items() if v not in (None, "")}
    understanding = None
    if reqs:
        pa = analyze_parameters(reqs, resolve_source_mappings(db, [q.evidence_type for q in reqs]), params)
        understanding = {
            "query_type_label": query_type_label(r.query_type),
            "parameters": [{"param": k, "label": intake.PARAM_LABELS.get(k, k.replace("_", " ").title()), "value": str(v)}
                           for k, v in params.items() if k not in ("period_start", "period_end")],
            "period": intake._period_text(params),
            "evidence_requested": [{"evidence_type": q.evidence_type, "label": evidence_label(q.evidence_type)} for q in reqs],
            "required_parameters": pa["required_parameters"],
            "parameter_status": "ACTION_REQUIRED" if pa["missing_parameters"] else "COMPLETE",
        }
    out = request_summary(r, counts)
    out.update({
        "understanding": understanding,
        "auditor_name": auditor.full_name if auditor else None,
        "parameters": sq.get("parameters", sq.get("known_identifiers", {})),
        "stepper": stepper(r.status),
        "evidence": evidence,
        "events": [event_view(e) for e in events],
        "validated_by": (review_pkg or {}).get("request_summary", {}).get("validated_by"),
        "validator_note": (review_pkg or {}).get("request_summary", {}).get("validator_note"),
        "validated_at": (review_pkg or {}).get("created_at"),
        "decisions": decisions,
        "has_review_package": bool(r.review_package_path),
        "has_final_package": bool(r.final_response_path),
        "actions": _actions(r, user),
    })
    return out


@router.get("/{rid}/events")
def events(rid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _load_for(db, rid, user)
    rows = db.scalars(select(RequestEvent).where(RequestEvent.request_id == rid).order_by(RequestEvent.created_at, RequestEvent.event_id))
    return [event_view(e) for e in rows]


@router.get("/{rid}/trail.csv")
def trail(rid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _load_for(db, rid, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Timestamp (UTC)", "Stage", "Event", "Detail", "Actor", "Role"])
    for e in db.scalars(select(RequestEvent).where(RequestEvent.request_id == rid).order_by(RequestEvent.created_at, RequestEvent.event_id)):
        w.writerow([iso(e.created_at), e.stage, e.title, e.detail or "", e.actor_name or "", e.actor_role or ""])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{rid}_audit_trail.csv"'})


# ---- human validation actions ------------------------------------------------------------------

class RetryBody(BaseModel):
    evidence_types: list[str] | None = None


class AcceptBody(BaseModel):
    evidence_type: str
    justification: str


class ContinueBody(BaseModel):
    note: str | None = None


class DecisionBody(BaseModel):
    comment: str | None = None


@router.post("/{rid}/retry")
def retry(rid: str, background: BackgroundTasks, body: RetryBody | None = None, db: Session = Depends(get_db),
          user: User = Depends(require_role("VALIDATOR"))):
    targets = service.request_retry(db, rid, user, (body.evidence_types if body else None))
    db.commit()
    background.add_task(graph.run, rid, "retry", targets)
    return {"request_id": rid, "status": "PROCESSING", "targets": targets}


@router.post("/{rid}/evidence-upload")
async def evidence_upload(rid: str, evidence_type: str = Form(...), file: UploadFile = File(...),
                          notes: str | None = Form(None), source_reference: str | None = Form(None),
                          user: User = Depends(require_role("VALIDATOR"))):
    content = await file.read()
    with session_scope() as db:
        item = service.manual_upload(db, rid, user, evidence_type, file.filename or "upload.pdf", content, notes, source_reference)
        return {"request_id": rid, "evidence": evidence_view(item)}


@router.post("/{rid}/accept-not-required")
def accept_not_required(rid: str, body: AcceptBody, db: Session = Depends(get_db), user: User = Depends(require_role("VALIDATOR"))):
    item = service.accept_not_required(db, rid, user, body.evidence_type, body.justification)
    db.commit()
    return {"request_id": rid, "evidence": evidence_view(item)}


@router.post("/{rid}/continue")
def continue_(rid: str, body: ContinueBody | None = None, db: Session = Depends(get_db),
              user: User = Depends(require_role("VALIDATOR"))):
    result = service.continue_validation(db, rid, user, body.note if body else None)
    db.commit()
    return {"request_id": rid, "status": "REVIEW_READY", "validation": result}


# ---- SME decision ------------------------------------------------------------------------------

@router.post("/{rid}/open-review")
def open_review(rid: str, db: Session = Depends(get_db), user: User = Depends(require_role("SME"))):
    service.mark_sme_opened(db, rid, user)
    db.commit()
    return {"request_id": rid}


@router.post("/{rid}/approve")
def approve(rid: str, body: DecisionBody | None = None, user: User = Depends(require_role("SME"))):
    with session_scope() as db:
        service.approve(db, rid, user, body.comment if body else None)
    with session_scope() as db:
        service.finalize(db, rid)
        r = db_ops.get_request(db, rid)
        return {"request_id": rid, "status": r.status}


@router.post("/{rid}/reject")
def reject(rid: str, body: DecisionBody, db: Session = Depends(get_db), user: User = Depends(require_role("SME"))):
    service.reject(db, rid, user, body.comment or "")
    db.commit()
    return {"request_id": rid, "status": "REWORK_REQUIRED"}


@router.post("/{rid}/finalize")
def finalize(rid: str, user: User = Depends(require_role("SME", "VALIDATOR"))):
    with session_scope() as db:
        service.finalize(db, rid)
    return {"request_id": rid, "status": "COMPLETED"}


# ---- packages ----------------------------------------------------------------------------------

@router.get("/{rid}/package")
def package(rid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _load_for(db, rid, user)
    base = get_settings().app_base_url
    out = {"request_id": rid, "status": r.status, "final_package": builder.load_package(r.final_response_path)}
    if user.role == "AUDITOR":
        out["application_link"] = f"{base}/login?next=/requests/{rid}/package"
    else:
        out["review_package"] = builder.load_package(r.review_package_path)
        out["application_link"] = f"{base}/login?next=" + (f"/validation/requests/{rid}" if user.role == "VALIDATOR" else f"/approvals/requests/{rid}")
    if user.role == "AUDITOR" and not out["final_package"]:
        out["message"] = "The Final Response Package will be available once the SME approves the evidence."
    return out


@router.get("/{rid}/package/download")
def package_download(rid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = _load_for(db, rid, user)
    if not r.final_response_path:
        raise AppError("The Final Response Package is not available yet.", code="not_ready", status_code=409)
    data = builder.bundle_zip(rid)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{rid}_final_response_package.zip"'})

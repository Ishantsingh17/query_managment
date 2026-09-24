"""Role-aware KPI summaries, notification bell and system status."""
from datetime import datetime, timedelta, timezone

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.serializers import as_utc, iso
from app.db.models import ApprovalAction, EvidenceItem, NotificationEvent, RequestEvent, RequestRecord, User
from app.db.session import get_db
from app.mock_sources import store

router = APIRouter(prefix="/api", tags=["dashboard"])


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/dashboard/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.now(timezone.utc)
    all_reqs = list(db.scalars(select(RequestRecord)))
    mine = [r for r in all_reqs if r.auditor_id == user.user_id] if user.role == "AUDITOR" else all_reqs
    count = lambda rows, statuses: sum(1 for r in rows if r.status in statuses)  # noqa: E731

    this_m = _month_start(now)
    last_m = _month_start(this_m - timedelta(days=1))
    created_this = sum(1 for r in mine if as_utc(r.created_at) >= this_m)
    created_last = sum(1 for r in mine if last_m <= as_utc(r.created_at) < this_m)
    done = [r for r in mine if r.status in ("NOTIFIED", "COMPLETED")]
    on_time = sum(1 for r in done if as_utc(r.updated_at) - as_utc(r.created_at) <= timedelta(days=7))
    turnaround = sorted((as_utc(r.updated_at) - as_utc(r.created_at)).total_seconds() / 86400
                        for r in all_reqs if r.status in ("NOTIFIED", "COMPLETED"))
    median = round(turnaround[len(turnaround) // 2], 1) if turnaround else None

    out = {
        "role": user.role,
        "auditor": {
            "total": len(mine), "processing": count(mine, {"REQUEST_CREATED", "PROCESSING"}),
            "awaiting_review": count(mine, {"VALIDATION_PENDING", "REWORK_REQUIRED", "REVIEW_READY", "SME_REVIEW",
                                            "APPROVED", "FINAL_RESPONSE_READY"}),
            "completed": len(done), "mom_delta": created_this - created_last,
            "on_time_pct": round(100 * on_time / len(done)) if done else 100,
            "median_turnaround_days": median,
        },
        "badges": {
            "review_queue": count(all_reqs, {"VALIDATION_PENDING", "REWORK_REQUIRED", "REVIEW_READY"}),
            "needs_attention": count(all_reqs, {"VALIDATION_PENDING", "REWORK_REQUIRED"}),
            "approvals": count(all_reqs, {"REVIEW_READY", "SME_REVIEW"}),
        },
    }
    if user.role == "SME":
        actions = list(db.scalars(select(ApprovalAction)))
        q_start = now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        awaiting = [r for r in all_reqs if r.status in ("REVIEW_READY", "SME_REVIEW")]
        due_soon = sum(1 for r in awaiting if as_utc(r.created_at) + timedelta(days=7) - now <= timedelta(days=2))
        decision_days = []
        for a in actions:
            ready = db.scalar(select(RequestEvent.created_at).where(RequestEvent.request_id == a.request_id,
                                                                    RequestEvent.title == "Review package ready")
                              .order_by(RequestEvent.created_at))
            if ready:
                decision_days.append((as_utc(a.acted_at) - as_utc(ready)).total_seconds() / 86400)
        out["sme"] = {
            "awaiting": len(awaiting), "due_soon": due_soon,
            "approved": sum(1 for a in actions if a.action == "APPROVE" and as_utc(a.acted_at) >= q_start),
            "rejected": sum(1 for a in actions if a.action == "REJECT"),
            "total_reviewed": len(actions),
            "avg_days": round(sum(decision_days) / len(decision_days), 1) if decision_days else 0,
        }
    return out


# Workflow stages for the pipeline chart, in order (earliest -> done).
STAGES = {
    "processing": {"REQUEST_CREATED", "PROCESSING"},
    "validator": {"VALIDATION_PENDING", "REWORK_REQUIRED"},
    "sme": {"REVIEW_READY", "SME_REVIEW", "APPROVED", "FINAL_RESPONSE_READY"},
    "completed": {"NOTIFIED", "COMPLETED"},
}
MAX_WEEKS = 26


@router.get("/dashboard/charts")
def charts(period: Literal["last_30", "last_90", "all"] = "last_90", db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    """Dashboard charts: weekly intake by current workflow stage, and evidence outcome per source system."""
    now = datetime.now(timezone.utc)
    stmt = select(RequestRecord)
    if user.role == "AUDITOR":
        stmt = stmt.where(RequestRecord.auditor_id == user.user_id)
    reqs = list(db.scalars(stmt))
    if period != "all":
        since = now - timedelta(days=30 if period == "last_30" else 90)
        reqs = [r for r in reqs if as_utc(r.created_at) >= since]
    else:
        since = min((as_utc(r.created_at) for r in reqs), default=now)

    def week_of(dt: datetime) -> datetime:
        d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return d - timedelta(days=d.weekday())  # Monday

    first = max(week_of(since), week_of(now) - timedelta(weeks=MAX_WEEKS - 1))
    weeks, w = [], first
    while w <= week_of(now):
        weeks.append(w)
        w += timedelta(weeks=1)
    buckets = {wk: {k: 0 for k in STAGES} for wk in weeks}
    for r in reqs:
        wk = max(week_of(as_utc(r.created_at)), first)  # older requests (beyond the cap) fold into the first week
        stage = next((k for k, v in STAGES.items() if r.status in v), None)
        if stage:
            buckets[wk][stage] += 1

    sources: dict[str, dict[str, int]] = {}
    ids = [r.request_id for r in reqs]
    for item in db.scalars(select(EvidenceItem).where(EvidenceItem.request_id.in_(ids))) if ids else []:
        if not item.source_system:
            continue
        row = sources.setdefault(item.source_system, {"auto": 0, "resolved": 0, "missing": 0})
        key = {"AVAILABLE": "auto", "MISSING": "missing"}.get(item.validation_status, "resolved")
        row[key] += 1
    return {
        "period": period,
        "weeks": [{"week_start": wk.date().isoformat(), **buckets[wk]} for wk in weeks],
        "sources": sorted(({"source_system": k, **v} for k, v in sources.items()),
                          key=lambda x: -(x["auto"] + x["resolved"] + x["missing"])),
    }


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Bell: this user's recent notifications (their inbox + the event types addressed to their role)."""
    from urllib.parse import parse_qs, urlparse

    from app.notifications.service import EVENTS_BY_ROLE, TEMPLATES, recipient_for
    rows = db.scalars(select(NotificationEvent).where(NotificationEvent.recipient == recipient_for(user),
                                                      NotificationEvent.event_type.in_(EVENTS_BY_ROLE.get(user.role, [])))
                      .order_by(NotificationEvent.sent_at.desc()).limit(10))
    out = []
    for n in rows:
        nxt = parse_qs(urlparse(n.application_link).query).get("next", ["/"])[0]
        out.append({"id": n.notification_id, "request_id": n.request_id,
                    "title": TEMPLATES[n.event_type][1].split(" — ")[0].replace("{rid}", n.request_id),
                    "status": n.status, "link": nxt, "sent_at": iso(n.sent_at)})
    return out


@router.get("/system/status")
def system_status(_: User = Depends(current_user)):
    sources = store.list_sources()
    up = [s for s in sources if s["available"]]
    return {"operational": len(up) == len(sources), "connected": len(up), "total": len(sources),
            "sources": [{"source_system": s["source_system"], "available": bool(s["available"])} for s in sources]}

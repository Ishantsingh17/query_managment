"""Populate a demo dataset by running real requests through the workflow (no hand-written request rows).

Run:  python -m app.seed_demo            (adds demo requests)
      python -m app.seed_demo --reset    (wipes storage first)
"""
import argparse
import io
import shutil
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.models import ApprovalAction, NotificationEvent, RequestEvent, RequestRecord, User
from app.db.session import session_scope
from app.main import app, bootstrap
from app.mcp.gateway import McpGateway, set_gateway
from app.orchestrator import graph, service

SCENARIOS = [
    # (days_ago, query, identifiers, follow-up) — stakeholder Query Types only
    (14, "Trade payables balance confirmation for vendor 1004821 as at August 2026 — balance, ageing, APTB extract, "
         "contact details and signed confirmation letter.", {}, "approve"),
    (12, "Retrieve payment testing evidence for payment document 1900004533 for August 2026, including invoice, "
         "purchase order, goods receipt and payment approval.", {}, "approve"),
    (10, "Bank portal payment process walkthrough for payment document 1900004533, FY2026 — signatory email approval, "
         "IPAMS approval and board resolution limits.", {}, "approve"),
    (9, "Balance confirmation not received from Apex — alternate testing for outstanding item INV-2026-08560 "
        "(invoice, PO and GRN/SES).", {}, "reject"),
    (8, "Payment testing evidence for payment document 1900004521 — payment report, invoice, PO, GRN, approval, "
        "UTR and accounting entries.", {}, "upload_and_continue"),
    (7, "Trade payables balance confirmation for vendor 1004877 as at August 2026.", {}, None),
    (6, "Alternate testing for outstanding item INV-2026-08533 — confirmation unavailable; retrieve invoice, PO and GRN/SES.", {}, None),
    (5, "Payment testing for payment document 1900004552 for August 2026.", {}, None),
    (4, "Payment process walkthrough for payment document 1900004521, FY2026.", {}, None),
    (3, "Payment report / payment testing for payment document 1900004560.", {}, None),
    (2, "Trade payables balance confirmation pack for vendor 1004821 — second sample for the September close.", {}, None),
]


def _backdate(rid: str, days: int) -> None:
    shift = timedelta(days=days)
    with session_scope() as s:
        r = s.get(RequestRecord, rid)
        r.created_at = r.created_at - shift
        r.updated_at = r.updated_at - shift + timedelta(days=min(days, 3))
        # Spread the workflow over a few days so KPIs (turnaround, decision time) look realistic.
        for i, e in enumerate(s.query(RequestEvent).filter(RequestEvent.request_id == rid).order_by(RequestEvent.event_id)):
            e.created_at = e.created_at - shift + timedelta(hours=min(i * 6, days * 12))
        for a in s.query(ApprovalAction).filter(ApprovalAction.request_id == rid):
            a.acted_at = a.acted_at - shift + timedelta(days=min(days, 3))
        for n in s.query(NotificationEvent).filter(NotificationEvent.request_id == rid):
            if n.sent_at:
                n.sent_at = n.sent_at - shift + timedelta(days=min(days, 3))


def run(reset: bool) -> None:
    settings = get_settings()
    if reset and settings.storage_dir.exists():
        for sub in ("db", "evidence_staging", "packages"):
            shutil.rmtree(settings.storage_dir / sub, ignore_errors=True)
    settings.mock_latency_ms = 0
    settings.notification_provider = "console"  # seeding must not send real emails
    bootstrap()
    if reset:
        from app.mock_sources import store
        store.seed_sources(force=True)  # also resets simulated late-posting counters
    set_gateway(McpGateway(client=TestClient(app)))

    with session_scope() as s:
        auditor = s.get(User, "U-AUD-001")
        validator = s.get(User, "U-VAL-001")
        sme = s.get(User, "U-SME-001")

    for days, query, ids, follow in SCENARIOS:
        with session_scope() as s:
            r = service.create_request(s, auditor, query, ids, None)
            rid = r.request_id
        graph.run(rid, "full")
        with session_scope() as s:
            if follow == "approve":
                service.approve(s, rid, sme, "All sources reconciled — amounts match.")
        if follow == "approve":
            with session_scope() as s:
                service.finalize(s, rid)
        elif follow == "reject":
            with session_scope() as s:
                service.reject(s, rid, sme, "SES quantity does not agree to the invoice — please re-verify the service entry in GESS.")
        elif follow == "upload_and_continue":
            with session_scope() as s:
                service.manual_upload(s, rid, validator, "APPROVAL", "IPAMS-approval-signed.pdf",
                                      b"%PDF-1.4\n% signed approval placeholder\n", "Signed approval obtained from Finance Controller",
                                      "APR-771204")
            with session_scope() as s:
                service.continue_validation(s, rid, validator, "All sources reconciled")
        _backdate(rid, days)
        with session_scope() as s:
            print(f"{rid}  {s.get(RequestRecord, rid).status}")
    set_gateway(None)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    run(p.parse_args().reset)

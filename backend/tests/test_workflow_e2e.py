"""End-to-end workflow tests on the stakeholder Query Types (payment testing scenarios A–E and the other three types)."""
import io

from app.orchestrator import graph

PAYMENT_A = ("Retrieve payment testing evidence for payment document 1900004533 for August 2026, including invoice, "
             "purchase order, goods receipt and payment approval.")
PAYMENT_B = "Payment testing evidence for payment document 1900004521 — payment report, invoice, PO, GRN, approval, UTR."
PAYMENT_C = "Payment testing for payment document 1900004552 for August 2026."


def submit(client, headers, query, **identifiers):
    r = client.post("/api/requests", headers=headers, json={"query": query, "identifiers": identifiers})
    assert r.status_code == 201, r.text
    return r.json()["request_id"]


def detail(client, headers, rid):
    r = client.get(f"/api/requests/{rid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def by_type(d):
    return {e["evidence_type"]: e for e in d["evidence"]}


def mails(provider, fragment):
    return [m for m in provider.sent if fragment in m["subject"]]


# ---- Payment Report / Payment Testing ------------------------------------------------------------

def test_payment_testing_complete_multi_source_to_final_package(env, auditor, sme):
    """Scenarios A + D: every item available, retrieved from six source systems, through to the auditor email."""
    c, provider = env["client"], env["provider"]
    rid = submit(c, auditor, PAYMENT_A)
    d = detail(c, auditor, rid)
    assert d["status"] == "REVIEW_READY" and d["query_type"] == "PAYMENT_REPORT_PAYMENT_TESTING"
    ev = by_type(d)
    assert list(ev) == ["PAYMENT_REPORT", "INVOICE", "PO", "GRN_SES", "APPROVAL", "PAYMENT_ADVICE_UTR", "ACCOUNTING_ENTRY"]
    assert all(e["status"] == "AVAILABLE" for e in ev.values())
    assert {e["source_system"] for e in ev.values()} == {"ORACLE", "GROSS", "ARIBA", "GESS", "IPAMS", "GPS"}
    assert ev["PO"]["source_reference"] == "4500239012"  # PO Number [from INVOICE] — documented dependency
    assert d["understanding"]["parameter_status"] == "COMPLETE"

    sme_mail = mails(provider, "Evidence Review Package ready")
    assert len(sme_mail) == 1 and f"/login?next=/approvals/requests/{rid}" in sme_mail[0]["text"]
    assert not mails(provider, "evidence missing")  # no validator email when complete

    assert c.get(f"/api/evidence/{ev['INVOICE']['evidence_id']}/file", headers=auditor).status_code == 403
    c.post(f"/api/requests/{rid}/open-review", headers=sme)
    assert detail(c, sme, rid)["status"] == "SME_REVIEW"
    assert c.post(f"/api/requests/{rid}/approve", headers=sme, json={"comment": "All sources reconciled."}).status_code == 200
    d = detail(c, auditor, rid)
    assert d["status"] == "COMPLETED"
    pkg = c.get(f"/api/requests/{rid}/package", headers=auditor).json()
    assert len(pkg["final_package"]["approved_evidence"]) == 7 and pkg["final_package"]["checksum"]
    assert pkg["application_link"].endswith(f"/login?next=/requests/{rid}/package")
    auditor_mail = mails(provider, "Final Response Package approved")
    assert len(auditor_mail) == 1 and f"/login?next=/requests/{rid}/package" in auditor_mail[0]["text"]
    f = c.get(f"/api/evidence/{ev['INVOICE']['evidence_id']}/file", headers=auditor)
    assert f.status_code == 200 and f.content.startswith(b"%PDF")
    z = c.get(f"/api/requests/{rid}/package/download", headers=auditor)
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"


def test_missing_approval_emails_validator_then_manual_upload(env, auditor, validator, sme):
    """Scenario B: approval unavailable -> Rework Required -> validator email -> manual upload -> SME approval."""
    c, provider = env["client"], env["provider"]
    rid = submit(c, auditor, PAYMENT_B)
    d = detail(c, validator, rid)
    assert d["status"] == "REWORK_REQUIRED"
    ev = by_type(d)
    assert ev["APPROVAL"]["status"] == "MISSING" and "IPAMS" in ev["APPROVAL"]["reason"]
    assert all(e["status"] == "AVAILABLE" for k, e in ev.items() if k != "APPROVAL")
    assert d["counts"]["missing"] == 1 and d["counts"]["available"] == 6

    msg = mails(provider, "evidence missing")
    assert len(msg) == 1
    body = msg[0]["text"]
    assert rid in body and "Payment Report / Payment Testing" in body and "Payment Approval" in body
    assert f"/login?next=/validation/requests/{rid}" in body
    assert not mails(provider, "Evidence Review Package ready")

    queue = c.get("/api/requests?view=queue&page_size=50", headers=validator).json()["items"]
    assert next(r for r in queue if r["request_id"] == rid)["missing_evidence"] == ["IPAMS Approval"]
    assert c.post(f"/api/requests/{rid}/continue", headers=validator, json={}).status_code == 409
    r = c.post(f"/api/requests/{rid}/evidence-upload", headers=validator,
               data={"evidence_type": "APPROVAL", "notes": "Signed approval", "source_reference": "APR-771204"},
               files={"file": ("IPAMS-approval-signed.pdf", io.BytesIO(b"%PDF-1.4 signed approval"), "application/pdf")})
    assert r.status_code == 200, r.text
    assert by_type(detail(c, validator, rid))["APPROVAL"]["status"] == "MANUALLY_UPLOADED"
    assert c.post(f"/api/requests/{rid}/continue", headers=validator, json={"note": "Reconciled"}).status_code == 200
    d = detail(c, sme, rid)
    assert d["status"] == "REVIEW_READY" and d["validated_by"] == "David Okafor"
    assert c.post(f"/api/requests/{rid}/approve", headers=sme, json={}).status_code == 200
    assert detail(c, auditor, rid)["status"] == "COMPLETED"


def test_retry_recovers_temporarily_unavailable_grn(env, auditor, validator):
    """Scenario C: GRN posted late; retry retrieves it. PO number is re-derived from the stored invoice."""
    c = env["client"]
    rid = submit(c, auditor, PAYMENT_C)
    d = detail(c, validator, rid)
    assert d["status"] == "REWORK_REQUIRED" and by_type(d)["GRN_SES"]["status"] == "MISSING"
    r = c.post(f"/api/requests/{rid}/retry", headers=validator, json={})
    assert r.status_code == 200 and r.json()["targets"] == ["GRN_SES"]
    d = detail(c, validator, rid)
    assert d["status"] == "VALIDATION_PENDING" and by_type(d)["GRN_SES"]["status"] == "AVAILABLE"


def test_source_outage_is_retryable_and_recovers(env, auditor, validator):
    """Scenario E: GPS down -> payment advice/UTR missing (retryable) -> source back -> retry succeeds."""
    c = env["client"]
    c.post("/mock-api/_admin/sources/GPS/availability?available=false")
    rid = submit(c, auditor, PAYMENT_A)
    utr = by_type(detail(c, validator, rid))["PAYMENT_ADVICE_UTR"]
    assert utr["status"] == "MISSING" and "unavailable" in utr["reason"]
    c.post("/mock-api/_admin/sources/GPS/availability?available=true")
    c.post(f"/api/requests/{rid}/retry", headers=validator, json={})
    assert by_type(detail(c, validator, rid))["PAYMENT_ADVICE_UTR"]["status"] == "AVAILABLE"


def test_mismatched_invoice_po_leaves_po_and_grn_missing(env, auditor, validator):
    c = env["client"]
    rid = submit(c, auditor, "Payment report / payment testing for payment document 1900004560.")
    ev = by_type(detail(c, validator, rid))
    assert ev["PO"]["status"] == "MISSING" and "4500239200" in ev["PO"]["reason"]
    assert ev["GRN_SES"]["status"] == "MISSING"


# ---- Other stakeholder Query Types ---------------------------------------------------------------

def test_trade_payables_balance_confirmation(env, auditor, validator):
    c = env["client"]
    rid = submit(c, auditor, "Trade payables balance confirmation for vendor 1004821 as at August 2026.")
    d = detail(c, auditor, rid)
    assert d["query_type"] == "TRADE_PAYABLES_BALANCE_CONFIRMATION" and d["status"] == "REVIEW_READY"
    assert set(by_type(d)) == {"VENDOR_PAYABLE_BALANCE", "AGEING", "SIGNED_CONFIRMATION_LETTER", "APTB_LEDGER_EXTRACT",
                               "VENDOR_CONTACT_DETAILS"}
    assert by_type(d)["APTB_LEDGER_EXTRACT"]["payload_type"] == "CSV"
    rid2 = submit(c, auditor, "Trade payables balance confirmation for vendor 1004877 as at August 2026.")
    ev = by_type(detail(c, validator, rid2))
    assert ev["SIGNED_CONFIRMATION_LETTER"]["status"] == "MISSING"


def test_balance_confirmation_alternate_testing(env, auditor, validator):
    c = env["client"]
    q = "Balance confirmation not received — alternate testing for outstanding item INV-2026-08560."
    rid = submit(c, auditor, q)
    d = detail(c, auditor, rid)
    assert d["query_type"] == "BALANCE_CONFIRMATION_ALTERNATE_TESTING" and d["status"] == "REVIEW_READY"
    ev = by_type(d)
    assert list(ev) == ["INVOICE", "PO", "GRN_SES"]
    assert ev["GRN_SES"]["source_reference"] == "SES-77100231"
    rid2 = submit(c, auditor, "Alternate testing for outstanding item INV-2026-08533, confirmation unavailable.")
    ev = by_type(detail(c, validator, rid2))
    assert ev["INVOICE"]["status"] == "AVAILABLE" and ev["PO"]["status"] == "MISSING"


def test_bank_portal_payment_process_walkthrough(env, auditor, validator):
    c = env["client"]
    rid = submit(c, auditor, "Bank portal payment process walkthrough for payment document 1900004533, FY2026.")
    d = detail(c, auditor, rid)
    assert d["query_type"] == "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH" and d["status"] == "REVIEW_READY"
    assert set(by_type(d)) == {"SIGNATORY_EMAIL_APPROVAL", "IPAMS_APPROVAL", "BOARD_RESOLUTION_LIMITS"}
    rid2 = submit(c, auditor, "Payment process walkthrough for payment document 1900004521, FY2026.")
    ev = by_type(detail(c, validator, rid2))
    assert ev["IPAMS_APPROVAL"]["status"] == "MISSING" and ev["SIGNATORY_EMAIL_APPROVAL"]["status"] == "AVAILABLE"


# ---- Human validator / SME branches --------------------------------------------------------------

def test_accept_not_required_requires_justification_and_is_excluded_from_final(env, auditor, validator, sme):
    c = env["client"]
    rid = submit(c, auditor, PAYMENT_B)
    r = c.post(f"/api/requests/{rid}/accept-not-required", headers=validator, json={"evidence_type": "APPROVAL", "justification": ""})
    assert r.status_code == 400
    r = c.post(f"/api/requests/{rid}/accept-not-required", headers=validator,
               json={"evidence_type": "APPROVAL", "justification": "Approval held offline; covered by walkthrough"})
    assert r.status_code == 200
    assert c.post(f"/api/requests/{rid}/continue", headers=validator, json={}).status_code == 200
    assert detail(c, validator, rid)["counts"]["not_required"] == 1
    assert c.post(f"/api/requests/{rid}/approve", headers=sme, json={}).status_code == 200
    final = c.get(f"/api/requests/{rid}/package", headers=auditor).json()["final_package"]
    types = [e["evidence_type"] for e in final["approved_evidence"]]
    assert "APPROVAL" not in types and len(types) == 6  # only SME-approved, available evidence


def test_sme_rejection_requires_comment_emails_validator_and_resubmits(env, auditor, validator, sme):
    c, provider = env["client"], env["provider"]
    rid = submit(c, auditor, PAYMENT_A)
    assert c.post(f"/api/requests/{rid}/reject", headers=sme, json={"comment": " "}).status_code == 400
    assert c.post(f"/api/requests/{rid}/reject", headers=sme, json={"comment": "UTR does not match bank statement."}).status_code == 200
    d = detail(c, validator, rid)
    assert d["status"] == "REWORK_REQUIRED" and d["approval_status"] == "REJECTED"
    rework = mails(provider, "Returned for rework")
    assert len(rework) == 1 and "UTR does not match bank statement." in rework[0]["text"]
    assert c.post(f"/api/requests/{rid}/approve", headers=sme, json={}).status_code == 409
    completed = c.get("/api/requests?view=completed&page_size=50", headers=auditor).json()["items"]
    assert any(r["request_id"] == rid and r["decision"] == "REJECT" for r in completed)
    assert c.post(f"/api/requests/{rid}/continue", headers=validator, json={"note": "Re-verified"}).status_code == 200
    assert detail(c, sme, rid)["status"] == "REVIEW_READY"


def test_duplicate_submission_rejected(env, auditor):
    c = env["client"]
    submit(c, auditor, PAYMENT_A)
    r = c.post("/api/requests", headers=auditor, json={"query": PAYMENT_A})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_request"


def test_package_generation_failure_keeps_approved_and_can_regenerate(env, auditor, sme, monkeypatch):
    from app.packages import builder
    c = env["client"]
    rid = submit(c, auditor, PAYMENT_A)

    def boom(*a, **k):
        raise builder.PackageError("Disk unavailable")
    original = builder.build_final_package
    monkeypatch.setattr(builder, "build_final_package", boom)
    r = c.post(f"/api/requests/{rid}/approve", headers=sme, json={})
    assert r.status_code == 500 and r.json()["error"]["code"] == "package_failed"
    d = detail(c, sme, rid)
    assert d["status"] == "APPROVED" and d["actions"] == ["finalize"]
    monkeypatch.setattr(builder, "build_final_package", original)
    assert c.post(f"/api/requests/{rid}/finalize", headers=sme).status_code == 200
    assert detail(c, auditor, rid)["status"] == "COMPLETED"


def test_notification_failure_does_not_break_workflow(env, auditor, sme):
    c, provider = env["client"], env["provider"]
    provider.fail = True
    rid = submit(c, auditor, PAYMENT_A)
    d = detail(c, sme, rid)
    assert d["status"] == "REVIEW_READY" and d["notification_status"] == "SME_FAILED"


def test_unauthorized_api_access(env, auditor, validator, sme):
    c = env["client"]
    rid = submit(c, auditor, PAYMENT_B)
    assert c.post(f"/api/requests/{rid}/retry", headers=auditor, json={}).status_code == 403
    assert c.post(f"/api/requests/{rid}/approve", headers=validator, json={}).status_code == 403
    assert c.post(f"/api/requests/{rid}/evidence-upload", headers=sme, data={"evidence_type": "APPROVAL"},
                  files={"file": ("a.pdf", io.BytesIO(b"%PDF"), "application/pdf")}).status_code == 403
    assert c.post("/api/requests", headers=sme, json={"query": PAYMENT_A}).status_code == 403
    assert c.post("/api/requests/analyze", headers=validator, json={"query": PAYMENT_A}).status_code == 403
    assert c.get("/api/requests").status_code == 401


def test_workflow_crash_moves_to_rework_and_notifies_validator(env, auditor, monkeypatch):
    c, provider = env["client"], env["provider"]

    def crash(state):
        raise RuntimeError("boom")
    monkeypatch.setattr(graph, "_graph", None)
    monkeypatch.setattr(graph, "retrieve_node", crash)
    rid = submit(c, auditor, PAYMENT_A)
    d = detail(c, auditor, rid)
    assert d["status"] == "REWORK_REQUIRED"
    assert any(e["title"] == "Processing interrupted" for e in d["events"])
    assert mails(provider, "evidence missing")
    monkeypatch.setattr(graph, "_graph", None)

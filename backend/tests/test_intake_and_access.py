"""Conversational intake (Request Understanding), common-login redirects and notification routing."""
from app.core.config import get_settings


def analyze(c, h, query, **kw):
    r = c.post("/api/requests/analyze", headers=h, json={"query": query, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def login(c, email, next_path=None):
    r = c.post("/api/auth/login", json={"email": email, "password": "Password@123", "next": next_path})
    assert r.status_code == 200
    return r.json()


# ---- Conversational intake -----------------------------------------------------------------------

def test_missing_required_parameter_is_asked_for_and_blocks_retrieval(env, auditor):
    c = env["client"]
    u = analyze(c, auditor, "Give me payment testing evidence for August 2026.")
    assert u["query_type"] == "PAYMENT_REPORT_PAYMENT_TESTING" and u["period"] == "August 2026"
    assert u["parameter_status"] == "ACTION_REQUIRED" and u["retrieval_status"] == "WAITING_FOR_PARAMETERS"
    assert [m["param"] for m in u["missing_parameters"]] == ["payment_document_number"]
    assert u["message"] == ("I understood this as Payment Report / Payment Testing for August 2026, "
                            "but I need the Payment Document Number to continue.")
    assert [e["label"] for e in u["evidence_requested"]][:2] == ["Payment Report", "Invoice"]
    r = c.post("/api/requests", headers=auditor, json={"query": "Give me payment testing evidence for August 2026."})
    assert r.status_code == 422 and r.json()["error"]["code"] == "parameters_required"
    assert r.json()["error"]["details"]["missing_parameters"][0]["label"] == "Payment Document Number"


def test_conversational_parameter_supply_updates_structured_query_and_continues(env, auditor):
    c = env["client"]
    q = "Give me payment testing evidence for August 2026."
    u = analyze(c, auditor, q, identifiers={"payment_document_number": "1900004533"})
    assert u["parameter_status"] == "COMPLETE" and u["retrieval_status"] == "READY"
    assert {"param": "payment_document_number", "label": "Payment Document Number", "value": "1900004533"} in u["parameters"]
    assert u["required_parameters"] == [{"params": ["payment_document_number"], "label": "Payment Document Number",
                                         "satisfied": True, "value": "1900004533"}]
    r = c.post("/api/requests", headers=auditor, json={"query": q, "identifiers": {"payment_document_number": "1900004533"}})
    assert r.status_code == 201
    d = c.get(f"/api/requests/{r.json()['request_id']}", headers=auditor).json()
    assert d["status"] == "REVIEW_READY" and d["understanding"]["parameter_status"] == "COMPLETE"


def test_parameter_from_natural_language_is_used_automatically(env, auditor):
    u = analyze(env["client"], auditor, "Trade payables balance confirmation for vendor 1004821")
    assert u["retrieval_status"] == "READY" and u["required_parameters"][0]["value"] == "1004821"


def test_walkthrough_asks_for_fiscal_year(env, auditor):
    u = analyze(env["client"], auditor, "Bank portal payment process walkthrough for payment document 1900004533")
    assert [m["label"] for m in u["missing_parameters"]] == ["Fiscal Year"]


def test_alternate_testing_offers_alternative_key(env, auditor):
    u = analyze(env["client"], auditor, "Balance confirmation unavailable — alternate testing please")
    m = u["missing_parameters"][0]
    assert m["label"] == "Invoice Number" and m["alternatives"] == [{"param": "payment_document_number",
                                                                     "label": "Payment Document Number"}]


def test_ambiguous_request_asks_for_clarification_then_selection_resolves(env, auditor):
    c = env["client"]
    ids = {"payment_document_number": "1900004533", "fiscal_year": "2026"}
    u = analyze(c, auditor, "I need a payment testing walkthrough", identifiers=ids)
    assert u["retrieval_status"] == "NEEDS_CLARIFICATION"
    assert {x["value"] for x in u["candidates"]} == {"PAYMENT_REPORT_PAYMENT_TESTING", "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH"}
    u = analyze(c, auditor, "I need a payment testing walkthrough", identifiers=ids,
                query_type="PAYMENT_REPORT_PAYMENT_TESTING")
    assert u["retrieval_status"] == "READY"


def test_unsupported_request_is_refused(env, auditor):
    c = env["client"]
    u = analyze(c, auditor, "Vendor master review including bank detail changes for vendor 1004821")
    assert u["retrieval_status"] == "UNSUPPORTED" and "Payment Report / Payment Testing" in u["message"]
    r = c.post("/api/requests", headers=auditor, json={"query": "Vendor master review including bank detail changes"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "query_type_unsupported"
    r = c.post("/api/requests", headers=auditor, json={"query": "Payment testing for 1900004533 please", "query_type": "TRAVEL_EXPENSE"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "query_type_unsupported"


# ---- Common login / role-safe redirects ----------------------------------------------------------

def _rid(env, auditor):
    r = env["client"].post("/api/requests", headers=auditor, json={
        "query": "Payment testing evidence for payment document 1900004521 — invoice, PO, GRN, approval."})
    return r.json()["request_id"]


def test_common_login_redirects_each_role_to_its_destination(env, auditor):
    c = env["client"]
    rid = _rid(env, auditor)
    assert login(c, "david.okafor@company.com", f"/validation/requests/{rid}")["redirect"] == {
        "allowed": True, "redirect": f"/validation/requests/{rid}", "reason": None}
    assert login(c, "priya.raman@company.com")["redirect"]["redirect"] == "/approvals"
    assert login(c, "sarah.mitchell@company.com")["redirect"]["redirect"] == "/dashboard"
    # auditor package link before the final package exists -> sent to the request page instead
    res = login(c, "sarah.mitchell@company.com", f"/requests/{rid}/package")["redirect"]
    assert res["allowed"] and res["redirect"] == f"/requests/{rid}" and res["reason"] == "package_not_ready"


def test_role_safe_redirect_rejects_wrong_role_foreign_and_external_targets(env, auditor):
    c = env["client"]
    rid = _rid(env, auditor)
    res = login(c, "sarah.mitchell@company.com", f"/validation/requests/{rid}")["redirect"]
    assert res == {"allowed": False, "redirect": "/dashboard", "reason": "wrong_role", "required_role": "Human Validator"}
    res = login(c, "david.okafor@company.com", f"/approvals/requests/{rid}")["redirect"]
    assert not res["allowed"] and res["redirect"] == "/queue" and res["required_role"] == "Final Approver (SME)"
    for bad in ("https://evil.example/phish", "//evil.example", "/requests/AUD-2026-9999"):
        res = login(c, "sarah.mitchell@company.com", bad)["redirect"]
        assert not res["allowed"] and res["redirect"] == "/dashboard"


def test_resolve_next_for_signed_in_user_and_foreign_auditor_request(env, auditor, sme):
    c = env["client"]
    rid = _rid(env, auditor)
    r = c.get(f"/api/auth/resolve-next?next=/approvals/requests/{rid}", headers=sme).json()
    assert r["allowed"] and r["redirect"] == f"/approvals/requests/{rid}"
    from app.db.models import User
    from app.db.session import session_scope
    from app.core.security import hash_password
    with session_scope() as s:
        s.add(User(user_id="U-AUD-002", email="other.auditor@company.com", full_name="Other Auditor", role="AUDITOR",
                   title="Auditor", password_hash=hash_password("Password@123")))
    tok = login(c, "other.auditor@company.com")["token"]
    r = c.get(f"/api/auth/resolve-next?next=/requests/{rid}", headers={"Authorization": f"Bearer {tok}"}).json()
    assert r == {"allowed": False, "redirect": "/dashboard", "reason": "not_permitted"}
    assert c.get(f"/api/requests/{rid}", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


# ---- Notification routing ------------------------------------------------------------------------

def test_role_specific_dev_recipients_and_bell(env, auditor, validator, monkeypatch):
    c, provider = env["client"], env["provider"]
    s = get_settings()
    monkeypatch.setattr(s, "notify_validator_email", "validator.inbox@example.com")
    monkeypatch.setattr(s, "notify_sme_email", "sme.inbox@example.com")
    rid = _rid(env, auditor)  # approval missing -> validator email
    assert [m["to"] for m in provider.sent] == ["validator.inbox@example.com"]
    bell = c.get("/api/notifications", headers=validator).json()
    assert bell[0]["request_id"] == rid and bell[0]["link"] == f"/validation/requests/{rid}"
    assert c.get("/api/notifications", headers=auditor).json() == []


# ---- Guided demo: ask for parameter -> one document missing -> validator email -> retry ----------

def test_guided_demo_ask_then_missing_then_retry(env, auditor, validator):
    c, provider = env["client"], env["provider"]
    q = "Retrieve payment testing evidence for August 2026 — payment report, invoice, PO, goods receipt, approval, UTR and accounting entries."
    u = analyze(c, auditor, q)
    assert [m["label"] for m in u["missing_parameters"]] == ["Payment Document Number"]
    ids = {"payment_document_number": "1900004588"}
    assert analyze(c, auditor, q, identifiers=ids)["retrieval_status"] == "READY"
    rid = c.post("/api/requests", headers=auditor, json={"query": q, "identifiers": ids}).json()["request_id"]
    d = c.get(f"/api/requests/{rid}", headers=validator).json()
    status = {e["evidence_type"]: e["status"] for e in d["evidence"]}
    assert d["status"] == "REWORK_REQUIRED" and status["GRN_SES"] == "MISSING"
    assert [k for k, v in status.items() if v != "AVAILABLE"] == ["GRN_SES"]
    assert any("evidence missing" in m["subject"] and rid in m["text"] for m in provider.sent)
    assert c.post(f"/api/requests/{rid}/retry", headers=validator, json={}).json()["targets"] == ["GRN_SES"]
    d = c.get(f"/api/requests/{rid}", headers=validator).json()
    assert d["status"] == "VALIDATION_PENDING" and all(e["status"] == "AVAILABLE" for e in d["evidence"])
    # the reset switch re-arms the late posting so the demo can be repeated
    assert c.post("/mock-api/_admin/reset-late-postings").json() == {"reset": True}
    from app.mcp.gateway import get_gateway
    again = get_gateway().call_tool("gess_retrieve_evidence", {"operation": "/goods-receipts", "keys": {"po_number": "4500239288"}})
    assert not again.ok


def test_guided_demo_repeats_for_every_new_request_without_reset(env, auditor, validator):
    """Late postings are per request: a second demo run sees the GRN missing again, and its retry finds it."""
    c = env["client"]
    q = "Retrieve payment testing evidence for August 2026 — payment report, invoice, PO, goods receipt, approval, UTR and accounting entries."
    ids = {"payment_document_number": "1900004588"}
    for suffix in ("", " Second demo run."):  # different wording: identical resubmissions are rejected as duplicates
        rid = c.post("/api/requests", headers=auditor, json={"query": q + suffix, "identifiers": ids}).json()["request_id"]
        d = c.get(f"/api/requests/{rid}", headers=validator).json()
        assert d["status"] == "REWORK_REQUIRED"
        assert {e["evidence_type"]: e["status"] for e in d["evidence"]}["GRN_SES"] == "MISSING"
        assert c.post(f"/api/requests/{rid}/retry", headers=validator, json={}).json()["targets"] == ["GRN_SES"]
        assert c.get(f"/api/requests/{rid}", headers=validator).json()["status"] == "VALIDATION_PENDING"

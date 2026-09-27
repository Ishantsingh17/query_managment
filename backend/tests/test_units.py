"""Unit + configuration + connector-contract tests."""
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, select

from app.agents.classification import classify_query
from app.agents.query_understanding import understand_query
from app.agents.retrieval_agent import RetrievalAgent
from app.agents.retrieval_planning import build_plan
from app.core.models import EvidenceSourceMapping, RequirementItem
from app.db.models import EXPECTED_SCHEMAS, EvidenceSourceRegistry, QueryTypeDefinition, RequirementCatalog
from app.db.session import get_engine, session_scope
from app.db.stakeholder_config import QUERY_TYPE_DEFINITIONS, REQUIREMENT_CATALOG
from app.mcp.connectors import ConnectorResult
from app.mcp.gateway import get_gateway
from app.registry.resolution import (endpoint_path, key_to_param, parse_keys, query_type_catalog,
                                     query_type_definitions, resolve_requirements, resolve_source_mappings)
from app.validation.engine import validate_completeness

STAKEHOLDER_TYPES = {"TRADE_PAYABLES_BALANCE_CONFIRMATION", "BALANCE_CONFIRMATION_ALTERNATE_TESTING",
                     "PAYMENT_REPORT_PAYMENT_TESTING", "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH"}


def defs():
    with session_scope() as s:
        return query_type_definitions(s)


def catalog():
    with session_scope() as s:
        return query_type_catalog(s)


# ---- Configuration -------------------------------------------------------------------------------

def test_config_tables_have_exact_agreed_schemas(env):
    insp = inspect(get_engine())
    assert [c["name"] for c in insp.get_columns("requirement_catalog")] == [
        "requirement_id", "query_type", "evidence_type", "evidence_description"]
    assert [c["name"] for c in insp.get_columns("evidence_source_registry")] == [
        "evidence_type", "source_system", "source_usage_selection_rule", "retrieval_method",
        "search_retrieval_keys", "source_object_location", "expected_output_type"]
    for table in ("requirement_catalog", "evidence_source_registry"):
        assert [c["name"] for c in insp.get_columns(table)] == EXPECTED_SCHEMAS[table]


def test_only_stakeholder_query_types_are_loaded(env):
    with session_scope() as s:
        catalog_types = set(s.scalars(select(RequirementCatalog.query_type).distinct()))
        definition_types = set(s.scalars(select(QueryTypeDefinition.query_type)))
    assert catalog_types == definition_types == STAKEHOLDER_TYPES
    labels = {q["label"] for q in env["client"].get("/api/requests/query-types", headers=_auditor(env)).json()}
    assert labels == {"Trade Payables Balance Confirmation", "Balance Confirmation – Alternate Testing",
                      "Payment Report / Payment Testing", "Bank Portal / Payment Process Walkthrough"}


def test_seed_replaces_stale_configuration(env):
    from app.db.seed_config import seed_config
    with session_scope() as s:
        s.add(RequirementCatalog(requirement_id="REQ-OLD", query_type="TRAVEL_EXPENSE", evidence_type="RECEIPT",
                                 evidence_description="old demo row"))
    with session_scope() as s:
        seed_config(s)
    with session_scope() as s:
        assert s.get(RequirementCatalog, "REQ-OLD") is None
        assert len(list(s.scalars(select(RequirementCatalog)))) == len(REQUIREMENT_CATALOG)


def test_requirement_catalog_lookup(env):
    with session_scope() as s:
        payment = resolve_requirements(s, "PAYMENT_REPORT_PAYMENT_TESTING")
        walkthrough = resolve_requirements(s, "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH")
    assert [r.evidence_type for r in payment] == ["PAYMENT_REPORT", "INVOICE", "PO", "GRN_SES", "APPROVAL",
                                                  "PAYMENT_ADVICE_UTR", "ACCOUNTING_ENTRY"]
    assert [r.evidence_type for r in walkthrough] == ["SIGNATORY_EMAIL_APPROVAL", "IPAMS_APPROVAL", "BOARD_RESOLUTION_LIMITS"]
    automation = {d[0]: d[3] for d in QUERY_TYPE_DEFINITIONS}
    assert "Given Payment Document Number" in automation["PAYMENT_REPORT_PAYMENT_TESTING"]


def test_evidence_source_registry_lookup_and_documented_dependency(env):
    with session_scope() as s:
        maps = resolve_source_mappings(s, ["INVOICE", "PO", "GRN_SES", "APPROVAL"])
        rows = list(s.scalars(select(EvidenceSourceRegistry)))
    assert {et: [m.source_system for m in ms] for et, ms in maps.items()} == {
        "INVOICE": ["GROSS"], "PO": ["ARIBA"], "GRN_SES": ["GESS"], "APPROVAL": ["IPAMS"]}
    inv, po = maps["INVOICE"][0], maps["PO"][0]
    assert [[k.param for k in g] for g in inv.key_groups] == [["invoice_number", "payment_document_number"]]
    assert po.key_groups[0][0].param == "po_number" and po.key_groups[0][0].derived_from == "INVOICE"
    assert all(r.retrieval_method == "API" for r in rows)


def test_key_grammar_and_endpoint_parsing():
    groups = parse_keys("Invoice Number / Payment Document Number, Fiscal Year")
    assert [[k.param for k in g] for g in groups] == [["invoice_number", "payment_document_number"], ["fiscal_year"]]
    dep = parse_keys("PO Number [from INVOICE]")[0][0]
    assert (dep.param, dep.derived_from) == ("po_number", "INVOICE")
    assert key_to_param("Payment Document Number") == "payment_document_number"
    assert endpoint_path("GROSS Invoice API - GET /invoices") == "/invoices"


# ---- Understanding / classification --------------------------------------------------------------

def test_query_understanding_extracts_parameters():
    sq = understand_query("Retrieve payment testing evidence for payment document 1900004533 for August 2026, "
                          "including invoice, purchase order, goods receipt and payment approval.")
    assert sq.parameters["payment_document_number"] == "1900004533"
    assert sq.parameters["period_start"] == "2026-08-01" and sq.parameters["period_end"] == "2026-08-31"
    sq = understand_query("Walkthrough for FY2026, item inv-2026-08560, vendor 1004821")
    assert sq.parameters["fiscal_year"] == "2026" and sq.parameters["invoice_number"] == "INV-2026-08560"
    assert sq.parameters["vendor_id"] == "1004821"


@pytest.mark.parametrize("text,expected,status", [
    ("Retrieve payment testing evidence for payment document 1900004533", "PAYMENT_REPORT_PAYMENT_TESTING", "identified"),
    ("Trade payables balance confirmation for vendor 1004821", "TRADE_PAYABLES_BALANCE_CONFIRMATION", "identified"),
    ("Confirmation not received, do alternate testing on INV-2026-08560", "BALANCE_CONFIRMATION_ALTERNATE_TESTING", "identified"),
    ("Bank portal payment process walkthrough, FY2026", "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH", "identified"),
    ("I need a payment testing walkthrough", None, "ambiguous"),
    ("Show me the travel expense receipts for employee E-20413", None, "unsupported"),
    ("Vendor master review for vendor 1004821", None, "unsupported"),
])
def test_natural_language_query_type_identification(env, text, expected, status):
    c = classify_query(understand_query(text, None, catalog()), defs())
    assert (c.query_type, c.status) == (expected, status)


def test_user_selection_must_be_a_supported_type(env):
    assert classify_query(understand_query("anything"), defs(), "TRAVEL_EXPENSE").status == "invalid_selection"
    c = classify_query(understand_query("anything"), defs(), "PAYMENT_REPORT_PAYMENT_TESTING")
    assert c.query_type == "PAYMENT_REPORT_PAYMENT_TESTING" and c.method == "user_selected"


# ---- Validation / retrieval semantics ------------------------------------------------------------

def test_validation_engine_completeness_only():
    items = [SimpleNamespace(evidence_type="A", validation_status="AVAILABLE", validation_reason=None),
             SimpleNamespace(evidence_type="B", validation_status="MANUALLY_UPLOADED", validation_reason=None),
             SimpleNamespace(evidence_type="C", validation_status="NOT_REQUIRED", validation_reason="policy"),
             SimpleNamespace(evidence_type="D", validation_status="MISSING", validation_reason="Missing in IPAMS")]
    r = validate_completeness("R", ["A", "B", "C", "D"], items)
    assert not r.is_complete and r.missing_evidence == ["D"] and r.completeness_pct == 75
    assert validate_completeness("R", ["A", "B", "C"], items).is_complete


class StubGateway:
    """Returns canned connector results keyed by (source, operation)."""
    def __init__(self, table):
        self.table, self.calls = table, []

    def call_tool(self, name, args):
        src = name.removesuffix("_retrieve_evidence").upper()
        self.calls.append((src, args["operation"], dict(args["keys"])))
        rec = self.table.get((src, args["operation"]))
        if rec is None:
            return ConnectorResult(False, src, status_code=404, error="no record")
        return ConnectorResult(True, src, records=[rec], reference_field="ref", status_code=200)


def _mapping(et, src, rule, keys, path):
    from app.registry.resolution import parse_keys as pk
    groups = pk(keys)
    return EvidenceSourceMapping(evidence_type=et, source_system=src, source_usage_rule=rule, retrieval_method="API",
                                 retrieval_keys=[k.label for g in groups for k in g], key_groups=groups,
                                 source_object_location=f"API - GET {path}", expected_output_type="Structured data")


def test_retrieval_uses_only_documented_dependencies_and_source_usage_rules():
    reqs = [RequirementItem(requirement_id="R1", query_type="Q", evidence_type="INVOICE", evidence_description="x"),
            RequirementItem(requirement_id="R2", query_type="Q", evidence_type="PO", evidence_description="x"),
            RequirementItem(requirement_id="R3", query_type="Q", evidence_type="CONTRACT", evidence_description="x")]
    maps = {
        "INVOICE": [_mapping("INVOICE", "GROSS", "Must retrieve", "Payment Document Number", "/invoices"),
                    _mapping("INVOICE", "ORACLE", "Alternative - use only when GROSS has none", "Payment Document Number", "/ap/invoices")],
        "PO": [_mapping("PO", "ARIBA", "Must retrieve", "PO Number [from INVOICE]", "/purchase-orders"),
               _mapping("PO", "GPS", "Corroborating", "PO Number [from INVOICE]", "/purchase-orders")],
        # CONTRACT needs a PO number but the registry does NOT document a dependency -> must not be derived
        "CONTRACT": [_mapping("CONTRACT", "GRS", "Must retrieve", "PO Number", "/contracts")],
    }
    gw = StubGateway({
        ("ORACLE", "/ap/invoices"): {"ref": "INV-1", "po_number": "4500000001", "vendor_id": "1"},
        ("ARIBA", "/purchase-orders"): {"ref": "4500000001"},
        ("GPS", "/purchase-orders"): {"ref": "4500000001"},
        ("GRS", "/contracts"): {"ref": "CTR-1"},
    })
    params = {"payment_document_number": "1900000001"}
    raws, _ = RetrievalAgent(gw).execute(build_plan("R", reqs, maps, params), params)
    by = {r.evidence_type: r for r in raws}
    assert by["INVOICE"].found and by["INVOICE"].result.source_system == "ORACLE"  # alternative after primary miss
    assert by["PO"].found and by["PO"].keys_used == {"po_number": "4500000001"}
    assert by["PO"].corroboration == [{"source_system": "GPS", "matched": True, "reference": "4500000001"}]
    assert not by["CONTRACT"].found and "not available" in by["CONTRACT"].reason
    assert ("GRS", "/contracts", {"po_number": "4500000001"}) not in gw.calls


# ---- MCP / connectors ----------------------------------------------------------------------------

def test_mcp_tools_list_covers_all_sources(env):
    names = {t["name"] for t in get_gateway().list_tools()}
    assert names == {f"{s.lower()}_retrieve_evidence" for s in
                     ("ORACLE", "GRS", "VMS", "GESS", "LMS", "ARIBA", "GPS", "GROSS", "IPAMS")}


def test_connector_contract_success_not_found_and_outage(env):
    gw = get_gateway()
    ok = gw.call_tool("gross_retrieve_evidence", {"operation": "/invoices", "keys": {"payment_document_number": "1900004533"}})
    assert ok.ok and ok.reference_field == "invoice_number" and ok.records[0]["invoice_number"] == "INV-2026-08455"
    assert ok.documents["INV-2026-08455"].startswith(b"%PDF")
    missing = gw.call_tool("ipams_retrieve_evidence", {"operation": "/approvals", "keys": {"payment_document_number": "1900004521"}})
    assert not missing.ok and missing.status_code == 404 and not missing.source_error
    env["client"].post("/mock-api/_admin/sources/ARIBA/availability?available=false")
    down = gw.call_tool("ariba_retrieve_evidence", {"operation": "/purchase-orders", "keys": {"po_number": "4500239012"}})
    assert not down.ok and down.status_code == 503 and down.source_error
    assert not gw.call_tool("nope_retrieve_evidence", {"operation": "/x", "keys": {}}).ok


def test_mcp_http_jsonrpc(env, validator):
    c = env["client"]
    r = c.post("/mcp", headers=validator, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(r.json()["result"]["tools"]) == 9
    r = c.post("/mcp", headers=validator, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "vms_retrieve_evidence", "arguments": {"operation": "/vendor-contacts", "keys": {"vendor_id": "1004821"}}}})
    assert r.json()["result"]["structuredContent"]["records"][0]["vendor_name"] == "Northwind Industrial Supplies"


def test_login_and_session(env):
    c = env["client"]
    assert c.post("/api/auth/login", json={"email": "sarah.mitchell@company.com", "password": "wrong"}).status_code == 401
    assert c.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).json()["error"]["code"] == "session_expired"
    assert c.post("/api/auth/sso").status_code == 501


def test_gmail_api_provider_refreshes_token_and_sends(monkeypatch):
    import base64
    from email import message_from_bytes

    from app.notifications import service as notif
    calls = []

    class R:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, str(body)

        def json(self):
            return self._b

    def fake_post(url, **kw):
        calls.append((url, kw))
        return R(200, {"access_token": "at-123"}) if "token" in url else R(200, {"id": "m1"})
    monkeypatch.setattr(notif.httpx, "post", fake_post)
    notif.GmailApiProvider("sender@gmail.com", "cid", "csecret", "rtok").send("to@example.com", "Subj", "text", "<b>html</b>")
    assert calls[0][1]["data"]["refresh_token"] == "rtok"
    assert calls[1][1]["headers"]["Authorization"] == "Bearer at-123"
    msg = message_from_bytes(base64.urlsafe_b64decode(calls[1][1]["json"]["raw"]))
    assert msg["To"] == "to@example.com" and msg["Subject"] == "Subj"


def _auditor(env):
    r = env["client"].post("/api/auth/login", json={"email": "sarah.mitchell@company.com", "password": "Password@123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_dashboard_charts_endpoint(env):
    """Pipeline-by-week and evidence-by-source aggregates for the auditor dashboard charts."""
    from tests.conftest import login
    c = env["client"]
    auditor = login(c, "sarah.mitchell@company.com")
    for q in ("Retrieve payment testing evidence for payment document 1900004533 for August 2026.",
              "Payment testing evidence for payment document 1900004521 — payment report, invoice, PO, GRN, approval, UTR."):
        assert c.post("/api/requests", headers=auditor, json={"query": q}).status_code == 201
    d = c.get("/api/dashboard/charts?period=last_30", headers=auditor).json()
    assert d["period"] == "last_30" and 4 <= len(d["weeks"]) <= 6
    assert sum(w["processing"] + w["validator"] + w["sme"] + w["completed"] for w in d["weeks"]) == 2
    latest = d["weeks"][-1]
    assert latest["sme"] == 1 and latest["validator"] == 1  # complete -> review ready, missing approval -> rework
    by = {r["source_system"]: r for r in d["sources"]}
    assert by["IPAMS"] == {"source_system": "IPAMS", "auto": 1, "resolved": 0, "missing": 1}
    assert by["ORACLE"]["auto"] == 4 and d["sources"][0]["source_system"] == "ORACLE"  # sorted by volume
    other = login(c, "priya.raman@company.com")  # SME sees the whole portfolio, not scoped to an auditor
    assert c.get("/api/dashboard/charts?period=all", headers=other).status_code == 200
    assert c.get("/api/dashboard/charts?period=bogus", headers=auditor).status_code == 422

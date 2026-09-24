"""LLM agent tests using a scripted fake chat model (no network)."""
import json

import pytest
from langchain_core.messages import AIMessage

from app.agents import llm
from app.agents.llm_retrieval_agent import AgenticRetrievalAgent
from app.agents.query_understanding import understand_query
from app.agents.retrieval_planning import build_plan
from app.db.session import session_scope
from app.mcp.gateway import get_gateway
from app.registry.resolution import query_type_catalog, resolve_requirements, resolve_source_mappings


class FakeChat:
    """Minimal stand-in for a LangChain chat model: scripted tool calls + structured output."""

    def __init__(self, turns=None, structured=None, fail=False):
        self.turns = list(turns or [])
        self.structured = structured
        self.fail = fail
        self.seen_tool_results = []

    def bind_tools(self, tools):
        return self

    def with_structured_output(self, schema):
        fake = self

        class _S:
            def invoke(self, messages):
                if fake.fail:
                    raise RuntimeError("provider down")
                return schema(**fake.structured)
        return _S()

    def invoke(self, messages):
        if self.fail:
            raise RuntimeError("provider down")
        self.seen_tool_results = [json.loads(m.content) for m in messages if m.type == "tool"]
        return self.turns.pop(0) if self.turns else AIMessage("All evidence retrieved.")


def call(i, et, src, **keys):
    return {"name": "RetrieveEvidence", "args": {"evidence_type": et, "source_system": src, "keys": keys}, "id": f"c{i}"}


@pytest.fixture()
def fake(env):
    holder = {}

    def install(model):
        llm.set_chat_model(model)
        holder["m"] = model
        return model
    yield install
    llm.set_chat_model(None)


PT = "PAYMENT_REPORT_PAYMENT_TESTING"


def payment_plan(params):
    with session_scope() as s:
        reqs = resolve_requirements(s, PT)
        maps = resolve_source_mappings(s, [r.evidence_type for r in reqs])
    return build_plan("AUD-T", reqs, maps, params)


def test_llm_classification_constrained_to_catalog(fake):
    fake(FakeChat(structured={"query_type": "TRADE_PAYABLES_BALANCE_CONFIRMATION",
                              "classification_rationale": "Asks for vendor balance confirmation.", "vendor_id": "1004821"}))
    with session_scope() as s:
        catalog = query_type_catalog(s)
    sq = understand_query("Please get the confirmation pack for vendor 1004821", None, catalog)
    assert sq.method == "llm" and sq.query_type == "TRADE_PAYABLES_BALANCE_CONFIRMATION"
    assert sq.rationale == "Asks for vendor balance confirmation." and sq.parameters["vendor_id"] == "1004821"


def test_llm_schema_rejects_query_types_outside_catalog(fake):
    fake(FakeChat(structured={"query_type": "TRAVEL_EXPENSE"}))
    with session_scope() as s:
        sq = understand_query("Pull the receipts for E-20413", None, query_type_catalog(s))
    assert sq.method == "rules" and sq.query_type is None  # schema validation failed -> deterministic fallback


def test_llm_ambiguity_is_surfaced(fake, auditor):
    fake(FakeChat(structured={"query_type": PT, "ambiguous_between": [PT, "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH"]}))
    from app.orchestrator import intake
    with session_scope() as s:
        u = intake.analyze_request(s, "payment evidence for doc 1900004533", {}, None)
    assert u["retrieval_status"] == "NEEDS_CLARIFICATION" and len(u["candidates"]) == 2


def test_llm_cannot_inject_identifiers_absent_from_text(fake):
    fake(FakeChat(structured={"query_type": PT, "payment_document_number": "1999999999"}))
    with session_scope() as s:
        sq = understand_query("Payment testing for last month", None, query_type_catalog(s))
    assert "payment_document_number" not in sq.parameters


def test_llm_failure_falls_back_to_rules(fake):
    fake(FakeChat(fail=True))
    with session_scope() as s:
        sq = understand_query("Payment testing for payment document 1900004533", None, query_type_catalog(s))
    assert sq.method == "rules" and sq.parameters["payment_document_number"] == "1900004533"


def test_agentic_retrieval_uses_documented_dependency_and_guardrails(fake):
    params = {"payment_document_number": "1900004533"}
    model = fake(FakeChat(turns=[
        AIMessage("", tool_calls=[call(1, "INVOICE", "GROSS", payment_document_number="1900004533")]),
        AIMessage("", tool_calls=[
            call(2, "PO", "ARIBA", po_number="4599999999"),                   # invented identifier -> rejected
            call(3, "INVOICE", "SAP", payment_document_number="1900004533"),  # source not in plan -> rejected
            call(4, "APPROVAL", "IPAMS", po_number="4500239012"),             # wrong key for the mapping -> rejected
            call(5, "PO", "ARIBA", po_number="4500239012"),                   # documented [from INVOICE] -> ok
        ]),
        AIMessage("", tool_calls=[
            call(6, "GRN_SES", "GESS", po_number="4500239012"),
            call(7, "APPROVAL", "IPAMS", payment_document_number="1900004533"),
        ]),
    ]))
    raws, _ = AgenticRetrievalAgent(get_gateway()).execute(payment_plan(params), params)
    by = {r.evidence_type: r for r in raws}
    assert all(r.found for r in raws)  # untried types (report, UTR, accounting) completed deterministically
    assert by["PO"].keys_used == {"po_number": "4500239012"}
    errors = [r.get("error", "") for r in model.seen_tool_results]
    assert any("not known" in e for e in errors) and any("not in the retrieval plan" in e for e in errors)
    assert any("one key from each group" in e for e in errors)


def test_agentic_retrieval_falls_back_when_llm_errors(fake):
    fake(FakeChat(fail=True))
    params = {"payment_document_number": "1900004533"}
    raws, _ = AgenticRetrievalAgent(get_gateway()).execute(payment_plan(params), params)
    assert all(r.found for r in raws)


def test_full_workflow_with_llm_agents(env, fake, auditor):
    fake(FakeChat(structured={"query_type": PT, "classification_rationale": "Payment document sample."},
                  turns=[AIMessage("", tool_calls=[call(1, "INVOICE", "GROSS", payment_document_number="1900004533")]),
                         AIMessage("Invoice retrieved; remaining items left to the executor.")]))
    c = env["client"]
    r = c.post("/api/requests", headers=auditor, json={"query": "Please pull evidence for payment doc 1900004533."})
    assert r.status_code == 201, r.text
    d = c.get(f"/api/requests/{r.json()['request_id']}", headers=auditor).json()
    assert d["status"] == "REVIEW_READY"
    assert any("Payment document sample." in (e["detail"] or "") for e in d["events"])

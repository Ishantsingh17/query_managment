"""Application-level observability tests: the Audit Evidence Platform emits correlated LLM / agent / tool telemetry
through the generic observability module (local JSONL + LangSmith), and telemetry never changes workflow outcomes."""
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from observability import Redactor, configure_observability
from observability.adapters.file_adapter import JsonlFileSink
from observability.adapters.langsmith_adapter import LangSmithSink
from observability.query import read_events, validate_file

from app.agents import llm
from app.core.config import get_settings
from app.core.telemetry import setup_observability
from app.orchestrator import graph

PT = "PAYMENT_REPORT_PAYMENT_TESTING"
PAYMENT_A = ("Retrieve payment testing evidence for payment document 1900004533 for August 2026, including invoice, "
             "purchase order, goods receipt and payment approval.")
PAYMENT_B = "Payment testing evidence for payment document 1900004521 — payment report, invoice, PO, GRN, approval, UTR."
USAGE = {"input_tokens": 812, "output_tokens": 236, "total_tokens": 1048}
LS_KEY = "lsv2_pt_0123456789abcdef0123456789abcdef_0a"


class ScriptedChat(BaseChatModel):
    """A real LangChain chat model (callbacks, tracing, structured output) with scripted, usage-bearing replies."""

    responses: list = []
    fail: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.fail:
            raise TimeoutError("provider timed out")
        msg = self.responses.pop(0) if self.responses else AIMessage("Done.", usage_metadata=dict(USAGE))
        return ChatResult(generations=[ChatGeneration(message=msg)])


def qu_reply(query_type=PT, rationale="Payment document sample.", payment_document_number="1900004533"):
    return AIMessage("", usage_metadata=dict(USAGE), tool_calls=[{
        "name": "AuditQueryExtraction", "id": "qu-1",
        "args": {"query_type": query_type, "classification_rationale": rationale,
                 "payment_document_number": payment_document_number}}])


def retrieval_turns():
    call = {"name": "RetrieveEvidence", "id": "r-1",
            "args": {"evidence_type": "INVOICE", "source_system": "GROSS",
                     "keys": {"payment_document_number": "1900004533"}}}
    return [AIMessage("", tool_calls=[call], usage_metadata={"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}),
            AIMessage("Invoice retrieved; remaining items left to the executor.",
                      usage_metadata={"input_tokens": 420, "output_tokens": 15, "total_tokens": 435})]


@pytest.fixture()
def obs_log(env, tmp_path, monkeypatch):
    """Point the app's observability at a per-test JSONL file (optionally with extra env settings)."""
    path = tmp_path / "logs" / "llm_observability.jsonl"

    def configure(**env_vars):
        monkeypatch.setenv("OBSERVABILITY_LOG_FILE", str(path))
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        return setup_observability()

    manager = {"m": configure()}

    def read(request_id=None, reconfigure=None):
        manager["m"].flush()
        return read_events(path, request_id=request_id) if request_id else read_events(path)

    def reconfigure(**env_vars):
        manager["m"] = configure(**env_vars)
        return manager["m"]
    yield {"path": path, "read": read, "reconfigure": reconfigure, "manager": manager}
    llm.set_chat_model(None)


def submit(client, headers, query):
    r = client.post("/api/requests", headers=headers, json={"query": query})
    assert r.status_code == 201, r.text
    return r.json()["request_id"]


def of(events, event_type, **match):
    return [e for e in events if e["event_type"] == event_type and all(e.get(k) == v for k, v in match.items())]


def run_of(events, name, event_type="agent_started"):
    return next(e for e in events if e["event_type"] == event_type and e["name"] == name)


def bound_traces(events, request_id):
    """Traces bound to the request (the intake trace runs before the request id exists, then gets bound)."""
    return {e["trace_id"] for e in events if e["event_type"] == "correlation_linked" and e["request_id"] == request_id} |         {e["trace_id"] for e in events if e["request_id"] == request_id}


def is_subsequence(needles, haystack):
    it = iter(haystack)
    return all(any(n == h for h in it) for n in needles)


# ---- 26. Query Understanding LLM call ----------------------------------------------------------------

def test_query_understanding_llm_call_appears_with_usage(env, obs_log, auditor):
    llm.set_chat_model(ScriptedChat(responses=[qu_reply(), *retrieval_turns()]))
    rid = submit(env["client"], auditor, PAYMENT_A)
    ev = obs_log["read"](rid)
    qu = of(ev, "llm_call_completed", component="query_understanding_agent")
    assert len(qu) == 1
    call = qu[0]
    assert call["operation"] == "structured_query_generation" and call["status"] == "success"
    assert (call["input_tokens"], call["output_tokens"], call["total_tokens"]) == (812, 236, 1048)
    assert call["usage_source"] == "provider" and call["provider"] == "custom" and call["latency_ms"] >= 0
    assert call["trace_id"] in bound_traces(ev, rid) and call["framework_run_ids"]
    agent = run_of(ev, "query_understanding_agent")
    assert call["parent_run_id"] == agent["run_id"] and call["trace_id"] == agent["trace_id"]
    done = next(e for e in ev if e["event_type"] == "agent_completed" and e["run_id"] == agent["run_id"])
    assert done["attributes"]["llm_used"] is True and done["attributes"]["method"] == "llm"
    raw = obs_log["path"].read_text(encoding="utf-8")
    assert PAYMENT_A not in raw and "Payment document sample." not in raw  # capture disabled by default


# ---- 27. no rules-based fallback: a missing LLM is an error, and it is traced ----------------------

def test_no_llm_configured_is_reported_and_traced(env, obs_log, auditor):
    llm.set_chat_model(None)  # tests run with AEP_LLM_PROVIDER=none
    r = env["client"].post("/api/requests", headers=auditor, json={"query": PAYMENT_A})
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"
    ev = obs_log["read"]()
    failed = of(ev, "agent_failed", name="query_understanding_agent")
    assert failed and failed[0]["error_type"] == "LlmUnavailableError"
    assert of(ev, "workflow_failed", name="request_intake")


# ---- 28. Retrieval planning / agentic retrieval LLM steps -----------------------------------------------

def test_retrieval_planning_is_deterministic_and_agentic_llm_steps_are_visible(env, obs_log, auditor):
    llm.set_chat_model(ScriptedChat(responses=[qu_reply(), *retrieval_turns()]))
    rid = submit(env["client"], auditor, PAYMENT_A)
    ev = obs_log["read"](rid)
    wf = run_of(ev, "audit_evidence_workflow", "workflow_started")
    planning = [e for e in ev if e["name"] == "retrieval_planning" and e["trace_id"] == wf["trace_id"]]
    assert [e["event_type"] for e in planning] == ["agent_started", "agent_completed"]
    assert planning[1]["attributes"]["llm_used"] is False and planning[1]["attributes"]["plan_steps"] > 0
    assert not [e for e in ev if e["run_type"] == "llm" and e["parent_run_id"] == planning[0]["run_id"]]

    retrieval = run_of(ev, "retrieval_agent")
    steps = of(ev, "llm_call_completed", component="retrieval_agent")
    assert [s["operation"] for s in steps] == ["evidence_tool_selection"] * 2
    assert all(s["parent_run_id"] == retrieval["run_id"] for s in steps)
    assert [s["total_tokens"] for s in steps] == [320, 435]
    first_llm = steps[0]["run_id"]
    invoice_tool = of(ev, "tool_call_completed", connector="GROSS")
    assert invoice_tool[0]["parent_llm_run_id"] == first_llm  # MCP call linked to the LLM run that requested it
    assert invoice_tool[0]["parent_run_id"] == retrieval["run_id"]


# ---- 29. MCP tool telemetry --------------------------------------------------------------------------

def test_mcp_tool_invocations_are_tool_telemetry(env, obs_log, auditor):
    rid = submit(env["client"], auditor, PAYMENT_A)
    ev = obs_log["read"](rid)
    tools = of(ev, "tool_call_completed")
    assert {t["connector"] for t in tools} == {"ORACLE", "GROSS", "ARIBA", "GESS", "IPAMS", "GPS"}
    assert all(t["run_type"] == "tool" and t["tool_name"].endswith("_retrieve_evidence") for t in tools)
    assert all(t["component"] == "mcp_gateway" and t["provider"] is None and t["model"] is None for t in tools)
    assert all(t["attributes"]["found"] is True and t["latency_ms"] >= 0 for t in tools)
    assert not of(ev, "llm_call_started", component="mcp_gateway")
    assert "1900004533" not in json.dumps(tools)  # key values are payload: not captured unless enabled


# ---- 30. complete request correlated by request id ------------------------------------------------------

def test_complete_request_correlated_by_request_id_in_single_file(env, obs_log, auditor):
    llm.set_chat_model(ScriptedChat(responses=[qu_reply(), *retrieval_turns()]))
    rid = submit(env["client"], auditor, PAYMENT_A)
    ev = obs_log["read"](rid)
    assert {e["name"] for e in of(ev, "workflow_completed")} == {"request_intake", "audit_evidence_workflow"}
    intake = run_of(ev, "request_intake", "workflow_started")
    link = of(ev, "correlation_linked", trace_id=intake["trace_id"], reason="request_bound")
    assert link and link[0]["request_id"] == rid  # intake trace bound once the request record exists
    after_bind = ev[ev.index(link[0]):]
    assert all(e["request_id"] == rid for e in after_bind)
    assert {e["trace_id"] for e in ev} == bound_traces(ev, rid)
    sequence = [(e["event_type"], e.get("name")) for e in ev]
    expected = [
        ("workflow_started", "request_intake"), ("agent_started", "query_understanding_agent"),
        ("llm_call_started", "query_understanding_agent.structured_query_generation"),
        ("llm_call_completed", "query_understanding_agent.structured_query_generation"),
        ("agent_completed", "query_understanding_agent"), ("agent_started", "query_type_classification"),
        ("agent_completed", "query_type_classification"), ("workflow_completed", "request_intake"),
        ("workflow_started", "audit_evidence_workflow"), ("agent_started", "retrieval_planning"),
        ("agent_completed", "retrieval_planning"), ("agent_started", "retrieval_agent"),
        ("llm_call_completed", "retrieval_agent.evidence_tool_selection"), ("tool_call_started", "gross_retrieve_evidence"),
        ("tool_call_completed", "gross_retrieve_evidence"), ("agent_completed", "retrieval_agent"),
        ("agent_started", "completeness_validation"), ("validation_event", "completeness_check"),
        ("agent_started", "final_packaging"), ("workflow_completed", "audit_evidence_workflow"),
    ]
    assert is_subsequence(expected, sequence), sequence
    valid, invalid = validate_file(obs_log["path"])
    assert invalid == [] and valid >= len(ev) > 20
    assert [p.name for p in obs_log["path"].parent.iterdir()] == ["llm_observability.jsonl"]
    assert env["client"].get(f"/api/requests/{rid}", headers=auditor).json()["status"] == "REVIEW_READY"


# ---- 31. failed request ----------------------------------------------------------------------------

def test_failed_request_retains_observability_data(env, obs_log, auditor, monkeypatch):
    def crash(state):
        raise RuntimeError("boom")
    monkeypatch.setattr(graph, "_graph", None)
    monkeypatch.setattr(graph, "retrieve_node", crash)
    rid = submit(env["client"], auditor, PAYMENT_A)
    ev = obs_log["read"](rid)
    failed = of(ev, "workflow_failed", name="audit_evidence_workflow")
    assert failed and failed[0]["request_id"] == rid and failed[0]["error_type"] == "RuntimeError"
    assert failed[0]["error_message"] == "boom" and failed[0]["latency_ms"] >= 0
    assert of(ev, "agent_completed", name="retrieval_planning")  # work done before the failure is kept
    assert env["client"].get(f"/api/requests/{rid}", headers=auditor).json()["status"] == "REWORK_REQUIRED"
    monkeypatch.setattr(graph, "_graph", None)


# ---- 32. retries -------------------------------------------------------------------------------------

def test_retries_stay_linked_to_request_and_trace(env, obs_log, auditor, validator):
    c = env["client"]
    c.post("/mock-api/_admin/sources/GPS/availability?available=false")
    rid = submit(c, auditor, PAYMENT_A)
    ev = obs_log["read"](rid)
    wf = run_of(ev, "audit_evidence_workflow", "workflow_started")
    started, completed = of(ev, "retry_started"), of(ev, "retry_completed")
    assert started and completed and len(started) == len(completed)
    for e in started + completed:
        assert e["trace_id"] == wf["trace_id"] and e["request_id"] == rid
        assert e["component"] == "retrieval_agent" and e["operation"] == "gps_retrieve_evidence"
    assert started[0]["retry_number"] == 1 and started[0]["reason"] == "source_error"
    assert started[0]["previous_error_type"].startswith("HTTP_5")
    assert completed[0]["outcome"] == "source_error" and completed[0]["status"] == "failed"
    gps = of(ev, "tool_call_failed", connector="GPS")
    assert [t["retry_count"] for t in gps] == [0, 1]
    # validator-triggered retry: a new workflow run, same request id
    c.post("/mock-api/_admin/sources/GPS/availability?available=true")
    c.post(f"/api/requests/{rid}/retry", headers=validator, json={})
    ev = obs_log["read"](rid)
    runs = of(ev, "workflow_completed", name="audit_evidence_workflow")
    assert [r["operation"] for r in runs] == ["full", "retry"] and {r["request_id"] for r in runs} == {rid}
    assert of(ev, "tool_call_completed", connector="GPS")[-1]["attributes"]["found"] is True


# ---- LLM failure / fallback workflow ----------------------------------------------------------------

def test_llm_failure_is_reported_to_user_and_traced(env, obs_log, auditor):
    llm.set_chat_model(ScriptedChat(fail=True))
    r = env["client"].post("/api/requests", headers=auditor, json={"query": PAYMENT_A})
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"
    assert "did not respond in time" in r.json()["error"]["message"]
    ev = obs_log["read"]()
    qu_failed = of(ev, "llm_call_failed", component="query_understanding_agent")
    assert qu_failed and qu_failed[0]["error_type"] == "TimeoutError" and qu_failed[0]["latency_ms"] >= 0
    assert of(ev, "agent_failed", name="query_understanding_agent")
    assert env["client"].get("/api/requests", headers=auditor).json()["items"] == []  # no request was created


# ---- missing evidence workflow ----------------------------------------------------------------------

def test_missing_evidence_workflow_is_observable(env, obs_log, auditor):
    rid = submit(env["client"], auditor, PAYMENT_B)
    ev = obs_log["read"](rid)
    v = of(ev, "validation_event", name="completeness_check")
    assert v and v[0]["outcome"] == "incomplete" and v[0]["attributes"]["missing"] == 1
    ipams = [t for t in of(ev, "tool_call_completed", connector="IPAMS")]
    assert ipams and ipams[0]["attributes"]["found"] is False  # "no record" is not a tool failure
    assert of(ev, "workflow_completed", name="audit_evidence_workflow")
    assert env["client"].get(f"/api/requests/{rid}", headers=auditor).json()["status"] == "REWORK_REQUIRED"


# ---- secrets / capture ------------------------------------------------------------------------------

def test_app_secrets_never_appear_even_with_capture_enabled(env, obs_log, auditor, monkeypatch):
    monkeypatch.setenv("AEP_GMAIL_APP_PASSWORD", "gmail-app-secret-1234")
    monkeypatch.setenv("AEP_GMAIL_OAUTH_REFRESH_TOKEN", "session-signing-secret-5678")
    obs_log["reconfigure"](OBSERVABILITY_CAPTURE_INPUTS="true", OBSERVABILITY_CAPTURE_OUTPUTS="true",
                           OBSERVABILITY_CAPTURE_MESSAGES="true")
    llm.set_chat_model(ScriptedChat(responses=[qu_reply(), *retrieval_turns()]))
    query = PAYMENT_A + " Contact ops.lead@company.com, pwd gmail-app-secret-1234, sig session-signing-secret-5678."
    rid = submit(env["client"], auditor, query)
    ev = obs_log["read"](rid)
    raw = obs_log["path"].read_text(encoding="utf-8")
    for secret in ("gmail-app-secret-1234", "session-signing-secret-5678", "ops.lead@company.com"):
        assert secret not in raw
    qu = of(ev, "llm_call_completed", component="query_understanding_agent")[0]
    assert qu["input_captured"] is True and qu["messages"][0]["role"] == "system"
    assert "[REDACTED]" in qu["messages"][1]["content"] and "1900004533" in qu["messages"][1]["content"]


# ---- LangSmith hierarchy for a real workflow ---------------------------------------------------------

def test_langsmith_trace_hierarchy_for_workflow(env, obs_log, auditor, monkeypatch):
    import langsmith
    posts, patches = [], []
    monkeypatch.setattr(langsmith.Client, "_create_run", lambda self, rc, **_: posts.append(rc))
    monkeypatch.setattr(langsmith.Client, "_update_run", lambda self, ru, **_: patches.append(ru))
    manager = obs_log["reconfigure"](LANGSMITH_TRACING="true", LANGSMITH_API_KEY=LS_KEY, LANGSMITH_PROJECT="aep-tests")
    settings, redactor = manager.settings, manager.redactor
    configure_observability(settings, redactor=redactor, sinks=[
        JsonlFileSink(obs_log["path"]),
        LangSmithSink(settings, redactor, api_url="http://127.0.0.1:9", auto_batch_tracing=False)])
    obs_log["manager"]["m"] = __import__("observability").get_observability()
    llm.set_chat_model(ScriptedChat(responses=[qu_reply(), *retrieval_turns()]))
    rid = submit(env["client"], auditor, PAYMENT_A)
    obs_log["read"]()
    runs: dict[str, dict] = {}
    for p in posts:
        runs[str(p["id"])] = dict(p)
    for p in patches:
        runs.setdefault(str(p["id"]), {}).update({k: v for k, v in p.items() if v is not None})

    def ancestors(run):
        out = []
        while run.get("parent_run_id"):
            run = runs[str(run["parent_run_id"])]
            out.append(run["name"])
        return out

    roots = {r["name"] for r in runs.values() if not r.get("parent_run_id")}
    assert {"request_intake", "audit_evidence_workflow"} <= roots
    retrieval = next(r for r in runs.values() if r["name"] == "retrieval_agent")
    assert ancestors(retrieval)[-3:] == ["retrieve", "orchestrator", "audit_evidence_workflow"]
    children = [r for r in runs.values() if str(r.get("parent_run_id")) == str(retrieval["id"])]
    assert {r["run_type"] for r in children} == {"llm", "tool"}
    assert len([r for r in children if r["run_type"] == "llm"]) == 2  # one LangSmith LLM run per model call
    assert any(r["name"] == "gross_retrieve_evidence" for r in children)
    qu_agent = next(r for r in runs.values() if r["name"] == "query_understanding_agent"
                    and ancestors(r)[-1:] == ["request_intake"])
    assert any(r["run_type"] == "llm" and qu_agent["name"] in ancestors(r) for r in runs.values())
    assert retrieval["extra"]["metadata"]["request_id"] == rid
    wf_root = next(r for r in runs.values() if r["name"] == "audit_evidence_workflow")
    assert wf_root["extra"]["metadata"]["request_id"] == rid
    blob = json.dumps([posts, patches], default=str)
    assert PAYMENT_A not in blob and LS_KEY not in blob  # capture off + secrets never sent

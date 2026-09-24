"""Unit tests: event model, span events, redaction, correlation, usage, errors, retries, fallbacks, configuration."""
import asyncio
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from observability import (REDACTED, EventType, ObservabilityError, ObservabilityEvent, ObservabilitySettings,
                           Redactor, RunType, TokenUsage, UsageSource)
from observability.metrics import estimate_cost, extract_usage
from observability.models import CORE_FIELDS, LLM_FIELDS
from observability.utils import iso_utc


def by_type(events, et):
    return [e for e in events if e["event_type"] == et]


def one(events, et):
    found = by_type(events, et)
    assert len(found) == 1, (et, [e["event_type"] for e in events])
    return found[0]


def fake_model(*messages):
    return GenericFakeChatModel(messages=iter(list(messages)))


# ---- 1. event model ----------------------------------------------------------------------------

def test_event_model_validation_and_stable_shape():
    e = ObservabilityEvent(event_type=EventType.AGENT_STARTED, run_type=RunType.AGENT, name="a")
    rec = e.to_record()
    assert set(CORE_FIELDS) <= set(rec) and rec["error_type"] is None and rec["latency_ms"] is None
    assert not set(LLM_FIELDS) & set(rec)  # usage fields only forced onto LLM events
    llm = ObservabilityEvent(event_type=EventType.LLM_CALL_COMPLETED, run_type=RunType.LLM).to_record()
    assert set(LLM_FIELDS) <= set(llm) and llm["input_tokens"] is None
    with pytest.raises(ValidationError):
        ObservabilityEvent(event_type="not_an_event")
    with pytest.raises(ValidationError):
        ObservabilityEvent(event_type=EventType.ERROR, latency_ms=-1)
    with pytest.raises(ValidationError):
        ObservabilityEvent(event_type=EventType.ERROR, unexpected_field=1)
    assert len({ObservabilityEvent(event_type=EventType.ERROR).event_id for _ in range(50)}) == 50


# ---- 2-4. span events ---------------------------------------------------------------------------

def test_llm_event_creation(make_obs, read):
    obs = make_obs()
    with obs.llm_call(component="qa", operation="answer", provider="openai", model="m-1") as call:
        call.set_response(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4, total_tokens=15)))
    ev = read(obs)
    start, end = ev
    assert start["event_type"] == "llm_call_started" and start["status"] == "started"
    assert end["event_type"] == "llm_call_completed" and end["status"] == "success"
    assert end["run_type"] == "llm" and end["provider"] == "openai" and end["model"] == "m-1"
    assert end["component"] == "qa" and end["operation"] == "answer" and end["retry_count"] == 0
    assert (end["input_tokens"], end["output_tokens"], end["total_tokens"], end["usage_source"]) == (11, 4, 15, "provider")
    assert end["run_id"] == start["run_id"] and end["latency_ms"] >= 0
    assert end["input_captured"] is False and end["output_captured"] is False


def test_agent_event_creation(make_obs, read):
    obs = make_obs()
    with obs.agent("planner", operation="plan") as a:
        a.annotate(llm_used=False, steps=3)
    ev = read(obs)
    assert [e["event_type"] for e in ev] == ["agent_started", "agent_completed"]
    assert ev[1]["agent_name"] == "planner" and ev[1]["attributes"] == {"llm_used": False, "steps": 3}
    assert ev[1]["run_type"] == "agent"


def test_tool_event_creation_links_parent_llm(make_obs, read):
    obs = make_obs()
    with obs.agent("retriever"):
        with obs.llm_call(component="retriever", operation="select_tool") as call:
            pass
        with obs.triggered_by_llm(call.run_id):
            with obs.tool_call("search", connector="SRC") as t:
                t.set_result(True, found=True, record_count=2)
        with obs.tool_call("search", connector="SRC") as t:
            t.set_result(False, "SourceUnreachable", "SRC could not be reached")
    ev = read(obs)
    ok, bad = by_type(ev, "tool_call_completed"), by_type(ev, "tool_call_failed")
    assert ok[0]["run_type"] == "tool" and ok[0]["connector"] == "SRC" and ok[0]["tool_name"] == "search"
    assert ok[0]["parent_llm_run_id"] == call.run_id and ok[0]["attributes"]["record_count"] == 2
    assert bad[0]["error_type"] == "SourceUnreachable" and bad[0].get("parent_llm_run_id") is None
    assert not [e for e in ev if e["run_type"] == "llm" and e.get("tool_name")]


# ---- 5-6. redaction ------------------------------------------------------------------------------

def test_redaction_masks_sensitive_values_and_keeps_usage_fields():
    r = Redactor(scan_environment=False)
    assert r.redact_text("Authorization: Bearer abc123def456") == "Authorization: [REDACTED]"
    assert "abc" not in r.redact_text("curl -H 'Bearer abcdefghijkl'")
    assert r.redact_text("Cookie: session=xyz; theme=dark") == "Cookie: [REDACTED]"
    assert r.redact_text("mail john.doe@example.com now") == "mail [REDACTED_EMAIL] now"
    assert r.redact_text("db password=hunter22&x=1") == "db password=[REDACTED]&x=1"
    assert r.redact_text("postgres://svc:s3cr3t@db:5432/x") == "postgres://svc:[REDACTED]@db:5432/x"
    for key in ("sk-proj-abcdefghijklmnopqrstu", "gsk_abcdefghijklmnopqrstuvwx", "lsv2_pt_abcdefghijklmnopqrstuvwxyz",
                "AKIAABCDEFGHIJKLMNOP", "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4fw"):
        assert r.redact_text(f"x {key} y") == f"x {REDACTED} y"
    nested = r.redact({"headers": {"Authorization": "Basic Zm9vOmJhcg==", "X-Api-Key": "k"},
                       "gmail_app_password": "abcd efgh", "input_tokens": 12, "max_tokens": 100,
                       "items": [{"refresh_token": "t"}, "ok"]})
    assert nested == {"headers": {"Authorization": REDACTED, "X-Api-Key": REDACTED}, "gmail_app_password": REDACTED,
                      "input_tokens": 12, "max_tokens": 100, "items": [{"refresh_token": REDACTED}, "ok"]}


def test_redaction_is_configurable():
    r = Redactor(scan_environment=False, extra_fields=["vendor_bank_ref"], extra_patterns=[r"\bEMP-\d{4}\b"],
                 redact_financial=True, redact_emails=False)
    assert r.redact({"vendor_bank_ref": "X1", "iban": "DE89370400440532013000"}) == {"vendor_bank_ref": REDACTED,
                                                                                    "iban": REDACTED}
    assert r.redact_text("employee EMP-1234 a@b.co") == f"employee {REDACTED} a@b.co"
    assert REDACTED in r.redact_text("card 4111 1111 1111 1111")
    off = Redactor(enabled=False, scan_environment=False)
    assert off.redact_text("a@b.co") == "a@b.co"  # optional rules off...
    assert off.redact_text("Bearer abcdefghijkl") == f"Bearer {REDACTED}"  # ...credential masking never off
    assert off.redact({"password": "x"}) == {"password": REDACTED}


def test_secret_masking_env_and_registered(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_API_KEY", "super-secret-value-123")
    monkeypatch.setenv("UNRELATED_SETTING", "plain-value-456")
    r = Redactor()
    r.register_secret("app-password-789")
    text = r.redact_text("keys super-secret-value-123 app-password-789 plain-value-456")
    assert text == f"keys {REDACTED} {REDACTED} plain-value-456"
    s = ObservabilitySettings(langsmith_api_key="lsv2_custom_key_value_1", langsmith_enabled=False)
    assert "lsv2_custom_key_value_1" not in repr(s) and "lsv2_custom_key_value_1" not in s.model_dump_json()
    assert Redactor.from_settings(s).redact_text("k=lsv2_custom_key_value_1") == f"k={REDACTED}"


# ---- 7. timestamps ------------------------------------------------------------------------------

def test_timestamp_handling(make_obs, read):
    assert iso_utc(datetime(2026, 9, 24, 12, 30, 45, 123456, tzinfo=timezone.utc)) == "2026-09-24T12:30:45.123Z"
    assert iso_utc(datetime(2026, 1, 1, 0, 0, 0)) == "2026-01-01T00:00:00.000Z"  # naive treated as UTC
    obs = make_obs()
    with obs.agent("a"):
        pass
    start, end = read(obs)
    for e in (start, end):
        assert e["timestamp"].endswith("Z") and len(e["timestamp"]) == 24
    assert end["start_time"] == start["start_time"] and end["end_time"] >= end["start_time"]


# ---- 8-9. correlation ---------------------------------------------------------------------------

def test_correlation_propagation_and_parent_child(make_obs, read):
    obs = make_obs()
    with obs.workflow("wf") as wf:
        with obs.agent("a1") as a1:
            obs.bind(request_id="REQ-1001")  # bound late, applies to the whole trace from here on
            with obs.llm_call(component="a1", operation="op") as llm:
                pass
            with obs.tool_call("t") as tool:
                pass
    ev = read(obs)
    assert {e["trace_id"] for e in ev} == {wf.trace_id} and wf.trace_id == wf.run_id  # trace id == root run id
    after_bind = ev[[e["event_type"] for e in ev].index("correlation_linked"):]
    assert all(e["request_id"] == "REQ-1001" for e in after_bind)
    parent = {e["run_id"]: e["parent_run_id"] for e in ev if e["event_type"].endswith("_started")}
    assert parent[wf.run_id] is None and parent[a1.run_id] == wf.run_id
    assert parent[llm.run_id] == a1.run_id and parent[tool.run_id] == a1.run_id


def test_concurrent_contexts_are_isolated(make_obs, read):
    obs = make_obs()

    def worker(i):
        with obs.workflow("wf", request_id=f"REQ-{i}"):
            with obs.agent("a"):
                with obs.llm_call(component="a", operation="x"):
                    pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    async def task(i):
        with obs.workflow("async_wf", request_id=f"AREQ-{i}"):
            await asyncio.sleep(0.001)
            with obs.agent("a"):
                await asyncio.sleep(0.001)

    async def main():
        await asyncio.gather(*(task(i) for i in range(10)))
    asyncio.run(main())
    ev = read(obs)
    traces: dict[str, set] = {}
    for e in ev:
        traces.setdefault(e["trace_id"], set()).add(e["request_id"])
    assert len(traces) == 30 and all(len(v) == 1 for v in traces.values())


# ---- 10-11. usage ---------------------------------------------------------------------------------

def test_token_usage_capture_from_langchain_callbacks(make_obs, read):
    obs = make_obs()
    model = fake_model(AIMessage("hi", usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
                                                       "input_token_details": {"cache_read": 8},
                                                       "output_token_details": {"reasoning": 2}}))
    with obs.llm_call(component="c", operation="o", provider="p", model="m") as call:
        call.set_response(model.invoke("hello"))  # usage already recorded by callback: must not double count
    end = one(read(obs), "llm_call_completed")
    assert (end["input_tokens"], end["output_tokens"], end["total_tokens"]) == (20, 5, 25)
    assert end["cached_tokens"] == 8 and end["reasoning_tokens"] == 2 and end["usage_source"] == "provider"
    assert end["framework_run_ids"] and end["attributes"]["framework"] == "langchain"


def test_usage_extraction_shapes():
    assert extract_usage({"usage": {"input_tokens": 3, "output_tokens": 1, "cache_read_input_tokens": 2}}).model_dump(
        include={"input_tokens", "output_tokens", "total_tokens", "cached_tokens"}) == {
        "input_tokens": 3, "output_tokens": 1, "total_tokens": 4, "cached_tokens": 2}
    oa = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2, total_tokens=9,
                                               prompt_tokens_details=SimpleNamespace(cached_tokens=5),
                                               completion_tokens_details=SimpleNamespace(reasoning_tokens=1)))
    u = extract_usage(oa)
    assert (u.input_tokens, u.output_tokens, u.cached_tokens, u.reasoning_tokens) == (7, 2, 5, 1)
    assert extract_usage(AIMessage("x")) is None and extract_usage("text") is None and extract_usage(None) is None


def test_missing_usage_is_null_not_invented_and_estimation_is_labelled(make_obs, read, log_path):
    obs = make_obs()
    with obs.llm_call(component="c", operation="o") as call:
        call.set_response(AIMessage("no usage reported"))
    end = one(read(obs), "llm_call_completed")
    assert end["input_tokens"] is None and end["output_tokens"] is None and end["total_tokens"] is None
    assert end["usage_source"] is None
    obs.shutdown()
    log_path.unlink()
    obs2 = make_obs(token_estimation_enabled=True)
    with obs2.llm_call(component="c", operation="o") as call:
        call.set_messages([("human", "x" * 400)])
        call.set_response(AIMessage("y" * 40))
    end = one(read(obs2), "llm_call_completed")
    assert end["usage_source"] == "estimated" and end["input_tokens"] == 100 and end["output_tokens"] == 10
    assert end["usage_details"]["estimation_method"] == "chars_div_4"
    assert (TokenUsage(input_tokens=1, source=UsageSource.ESTIMATED) + TokenUsage(input_tokens=1)).source == "estimated"


def test_cost_only_when_configured(make_obs, read, log_path):
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    assert estimate_cost(usage, "m", ObservabilitySettings(langsmith_enabled=False)) is None
    s = ObservabilitySettings(cost_tracking_enabled=True, input_cost_per_1k_tokens=0.5, output_cost_per_1k_tokens=1.0,
                              model_pricing={"big": {"input_cost_per_1k_tokens": 2.0, "output_cost_per_1k_tokens": 4.0}})
    assert estimate_cost(usage, "m", s) == (1.0, "USD", "configuration:default")
    assert estimate_cost(usage, "big", s) == (4.0, "USD", "configuration:model")
    obs = make_obs(cost_tracking_enabled=True, input_cost_per_1k_tokens=0.5, output_cost_per_1k_tokens=1.0)
    with obs.llm_call(component="c", operation="o", model="m") as call:
        call.set_usage(input_tokens=1000, output_tokens=500)
    end = one(read(obs), "llm_call_completed")
    assert end["estimated_cost"] == 1.0 and end["cost_currency"] == "USD" and end["pricing_source"].startswith("configuration")


# ---- 12. errors ------------------------------------------------------------------------------------

def test_error_serialization_and_reraise(make_obs, read):
    obs = make_obs()
    with pytest.raises(TimeoutError) as info:
        with obs.agent("a"):
            with obs.llm_call(component="a", operation="o", provider="openai", model="m"):
                raise TimeoutError("timed out calling https://api?api_key=sk-abcdefghijklmnopqrstuvwx\nline2")
    assert "sk-abcdefghijklmnopqrstuvwx" in str(info.value)  # the application sees its exception unchanged
    ev = read(obs)
    failed = one(ev, "llm_call_failed")
    assert failed["status"] == "failed" and failed["error_type"] == "TimeoutError" and failed["latency_ms"] >= 0
    assert "sk-abc" not in failed["error_message"] and "\n" not in failed["error_message"]
    assert one(ev, "agent_failed")["error_type"] == "TimeoutError"
    obs.log_error(ValueError("bad password=abc123"), component="a")
    err = one(read(obs), "error")
    assert err["error_type"] == "ValueError" and "abc123" not in err["error_message"]


# ---- 13-14. retries and fallbacks --------------------------------------------------------------------

def test_retry_events_stay_in_trace_and_mark_nested_calls(make_obs, read):
    obs = make_obs()
    with obs.workflow("wf", request_id="REQ-7") as wf:
        with obs.retry(component="retriever", operation="tool_x", retry_number=1, reason="source_error",
                       previous_error_type="HTTP_503") as r:
            with obs.tool_call("tool_x"):
                pass
            r.set_outcome("success")
        with obs.retry(component="retriever", operation="tool_x", retry_number=2, reason="source_error") as r:
            r.set_outcome("source_error")
    ev = read(obs)
    started, completed = by_type(ev, "retry_started"), by_type(ev, "retry_completed")
    assert [e["retry_number"] for e in started] == [1, 2] and started[0]["previous_error_type"] == "HTTP_503"
    assert [e["outcome"] for e in completed] == ["success", "source_error"]
    assert [e["status"] for e in completed] == ["success", "failed"]
    assert all(e["trace_id"] == wf.trace_id and e["request_id"] == "REQ-7" for e in started + completed)
    assert one(ev, "tool_call_started")["retry_count"] == 1


def test_rules_based_fallback_is_explicit(make_obs, read):
    obs = make_obs()
    with obs.agent("query_understanding", request_id="REQ-1001"):
        obs.log_fallback_started(component="query_understanding", fallback_type="rules_based", reason="llm_disabled")
        obs.log_fallback_completed(component="query_understanding", fallback_type="rules_based", reason="llm_disabled")
    ev = read(obs)
    start, done = one(ev, "llm_fallback_started"), one(ev, "llm_fallback_completed")
    assert start["fallback_type"] == done["fallback_type"] == "rules_based" and start["reason"] == "llm_disabled"
    assert done["workflow_continued"] is True and done["request_id"] == "REQ-1001"
    assert not by_type(ev, "llm_call_started")  # a rules-based execution is never reported as an LLM call


# ---- 15. configuration ------------------------------------------------------------------------------

def test_configuration_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERVABILITY_CAPTURE_INPUTS", "true")
    monkeypatch.setenv("OBSERVABILITY_REDACT_FIELDS", "vendor_ref, bank_ref")
    monkeypatch.setenv("OBSERVABILITY_REDACT_PATTERNS", '["\\\\bX-\\\\d+\\\\b"]')
    monkeypatch.setenv("LANGCHAIN_PROJECT", "legacy-name")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    s = ObservabilitySettings.load()
    assert s.capture_inputs and not s.capture_outputs and s.redact_fields == ["vendor_ref", "bank_ref"]
    assert s.redact_patterns == [r"\bX-\d+\b"] and s.langsmith_project == "legacy-name"
    assert s.langsmith_active is False  # tracing on but no API key -> LangSmith stays off
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")
    assert ObservabilitySettings.load().langsmith_active is True
    monkeypatch.setenv("LANGSMITH_ENABLED", "false")
    assert ObservabilitySettings.load().langsmith_active is False
    env_file = tmp_path / ".env"
    env_file.write_text("OBSERVABILITY_LOG_FILE=custom/obs.jsonl\n")
    assert ObservabilitySettings.load(env_file).resolved_log_file(tmp_path) == tmp_path / "custom" / "obs.jsonl"
    monkeypatch.delenv("OBSERVABILITY_CAPTURE_INPUTS")
    defaults = ObservabilitySettings(langsmith_enabled=False)
    assert (defaults.capture_inputs, defaults.capture_outputs, defaults.capture_messages) == (False, False, False)
    assert defaults.redaction_enabled and defaults.fail_open and not defaults.log_rotation_enabled


def test_invalid_configuration_falls_back_to_safe_defaults(monkeypatch, caplog):
    monkeypatch.setenv("OBSERVABILITY_QUEUE_SIZE", "not-a-number")
    s = ObservabilitySettings.load()
    assert s.config_errors == ["OBSERVABILITY_QUEUE_SIZE"] or s.config_errors  # reported, not raised
    assert s.enabled and s.queue_size == 10_000 and not s.capture_messages
    assert "invalid observability configuration" in caplog.text


def test_strict_mode_raises_and_disabled_mode_is_noop(make_obs, read, log_path):
    class Broken:
        name = "broken"

        def emit(self, event, span):
            raise RuntimeError("sink down")

        def start_span(self, span, event): ...
        def end_span(self, span, event): ...
        def flush(self, timeout=None): ...
        def shutdown(self): ...

    strict = make_obs(fail_open=False, sinks=[Broken()])
    with pytest.raises(ObservabilityError):
        with strict.agent("a"):
            pass
    off = make_obs(enabled=False)
    with off.workflow("wf") as wf, off.llm_call(component="c", operation="o") as call:
        call.set_response(AIMessage("x"))
        call.annotate(a=1)
    assert wf.run_id is None and off.sinks == () and not log_path.exists()

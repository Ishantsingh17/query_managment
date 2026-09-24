"""Integration tests: LangSmith adapter, local JSONL adapter, both together, failure isolation, concurrency,
redaction before persistence, secret hygiene, hierarchy, capture policy, framework integrations."""
import json
import threading

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from observability import ObservabilityManager, ObservabilitySettings, Redactor
from observability.adapters.file_adapter import JsonlFileSink
from observability.adapters.langsmith_adapter import LangSmithSink
from observability.integrations.langgraph import graph_config, observe_node
from observability.integrations.llm import call_llm, observed_llm
from observability.query import read_events, validate_file

LS_KEY = "lsv2_pt_0123456789abcdef0123456789abcdef_0a"


def ls_settings(log_path, **kw):
    return ObservabilitySettings(log_file=log_path, langsmith_tracing=True, langsmith_api_key=LS_KEY,
                                 langsmith_project="obs-tests", **kw)


def both_sinks(settings, log_path, redactor=None):
    redactor = redactor or Redactor.from_settings(settings)
    ls = LangSmithSink(settings, redactor, api_url="http://127.0.0.1:9", auto_batch_tracing=False)
    return ObservabilityManager(settings, sinks=[JsonlFileSink(log_path), ls], redactor=redactor), ls


def scenario(obs, model):
    with obs.workflow("wf", request_id="REQ-1001") as wf:
        with obs.agent("qa") as agent:
            with obs.llm_call(component="qa", operation="answer", provider="fake", model="m") as lc_call:
                lc_call.set_response(model.invoke([("human", "hello")]))
            with obs.llm_call(component="qa", operation="raw_sdk", provider="openai", model="gpt-x") as raw:
                raw.set_usage(input_tokens=10, output_tokens=4)
            with obs.triggered_by_llm(raw.run_id), obs.tool_call("mcp_tool", connector="SRC") as tool:
                tool.set_result(True, found=True)
    return wf, agent, lc_call, raw, tool


def usage_model():
    return GenericFakeChatModel(messages=iter([AIMessage("hi", usage_metadata={"input_tokens": 5, "output_tokens": 2,
                                                                                "total_tokens": 7})]))


# ---- 16/19/25. LangSmith enabled, both sinks, hierarchy --------------------------------------------

def test_langsmith_and_file_sinks_share_one_hierarchy(log_path, langsmith_capture):
    obs, _ = both_sinks(ls_settings(log_path), log_path)
    wf, agent, lc_call, raw, tool = scenario(obs, usage_model())
    obs.shutdown()
    runs = langsmith_capture["runs"]()
    by_name = {r["name"]: r for r in runs.values()}
    assert set(by_name) == {"wf", "qa", "GenericFakeChatModel", "qa.raw_sdk", "mcp_tool"}  # no duplicate LLM run
    assert all(str(r["trace_id"]) == wf.trace_id for r in runs.values())  # same trace id locally and remotely
    assert str(by_name["wf"]["id"]) == wf.run_id and by_name["wf"].get("parent_run_id") is None
    assert str(by_name["qa"]["parent_run_id"]) == wf.run_id
    for child in ("GenericFakeChatModel", "qa.raw_sdk", "mcp_tool"):
        assert str(by_name[child]["parent_run_id"]) == agent.run_id
    assert by_name["mcp_tool"]["run_type"] == "tool" and by_name["qa.raw_sdk"]["run_type"] == "llm"
    md = by_name["qa.raw_sdk"]["extra"]["metadata"]
    assert md["usage_metadata"] == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    assert md["ls_provider"] == "openai" and md["request_id"] == "REQ-1001"
    assert by_name["qa"]["extra"]["metadata"]["request_id"] == "REQ-1001"
    # LangChain's own LLM run keeps token usage even though output capture is off (content stripped)
    lc_out = by_name["GenericFakeChatModel"]["outputs"]
    assert lc_out["generations"][0][0]["message"]["kwargs"]["usage_metadata"]["total_tokens"] == 7
    assert lc_out["generations"][0][0]["text"] == ""
    # the local file carries the same run ids / parent links
    ev = read_events(log_path)
    local = {e["run_id"]: e["parent_run_id"] for e in ev if e["event_type"].endswith("_started")}
    assert local[agent.run_id] == wf.run_id and local[lc_call.run_id] == agent.run_id and local[tool.run_id] == agent.run_id
    lc_done = next(e for e in ev if e["run_id"] == lc_call.run_id and e["event_type"] == "llm_call_completed")
    assert lc_done["total_tokens"] == 7 and str(by_name["GenericFakeChatModel"]["id"]) in lc_done["framework_run_ids"]
    tool_done = next(e for e in ev if e["event_type"] == "tool_call_completed")
    assert tool_done["parent_llm_run_id"] == raw.run_id


# ---- 17. LangSmith disabled -----------------------------------------------------------------------

def test_langsmith_disabled_means_no_remote_sink(log_path, langsmith_capture, caplog):
    for s in (ObservabilitySettings(log_file=log_path, langsmith_enabled=False, langsmith_tracing=True,
                                    langsmith_api_key=LS_KEY),
              ObservabilitySettings(log_file=log_path, langsmith_tracing=False, langsmith_api_key=LS_KEY),
              ObservabilitySettings(log_file=log_path, langsmith_tracing=True)):
        obs = ObservabilityManager(s)
        assert [k.name for k in obs.sinks] == ["file"]
        scenario(obs, usage_model())
        obs.shutdown()
    assert langsmith_capture["posts"] == [] and langsmith_capture["patches"] == []
    assert "LANGSMITH_API_KEY is not set" in caplog.text


def test_langsmith_enabled_via_settings_builds_sink(log_path):
    obs = ObservabilityManager(ls_settings(log_path))
    assert [k.name for k in obs.sinks] == ["file", "langsmith"]
    obs.shutdown()


# ---- 18. local JSONL -------------------------------------------------------------------------------

def test_local_jsonl_single_file_multiple_events(make_obs, log_path):
    obs = make_obs()
    for i in range(3):
        scenario(obs, usage_model())
    obs.shutdown()
    files = list(log_path.parent.iterdir())
    assert files == [log_path]  # exactly one file, no per-request/agent/day files
    valid, invalid = validate_file(log_path)
    assert invalid == [] and valid == 3 * 10


def test_rotation_is_opt_in_and_bounded(tmp_path):
    path = tmp_path / "obs.jsonl"
    sink = JsonlFileSink(path, rotation_enabled=True, max_bytes=2048, backup_count=2)
    obs = ObservabilityManager(ObservabilitySettings(log_file=path, langsmith_enabled=False), sinks=[sink])
    for _ in range(60):
        with obs.agent("a" * 50):
            pass
        obs.flush()
    obs.shutdown()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["obs.jsonl", "obs.jsonl.1", "obs.jsonl.2"]
    for p in tmp_path.iterdir():
        assert validate_file(p)[1] == []


# ---- 20-21. failure isolation -------------------------------------------------------------------------

def test_langsmith_failure_does_not_fail_workflow(log_path, monkeypatch):
    import langsmith

    def boom(self, *a, **k):
        raise ConnectionError("LangSmith unreachable")
    monkeypatch.setattr(langsmith.Client, "_create_run", boom)
    monkeypatch.setattr(langsmith.Client, "_update_run", boom)
    obs, _ = both_sinks(ls_settings(log_path), log_path)
    result = None
    with obs.workflow("wf", request_id="REQ-2"):
        with obs.llm_call(component="c", operation="o") as call:
            result = usage_model().invoke("hi")
            call.set_response(result)
    obs.shutdown()
    assert result.content == "hi"  # the LLM call and workflow completed
    ev = read_events(log_path)
    assert [e["event_type"] for e in ev if e["event_type"].startswith("workflow")] == ["workflow_started", "workflow_completed"]
    errs = [e for e in ev if e["event_type"] == "observability_error"]
    assert errs and all(e["attributes"]["sink"] == "langsmith" for e in errs)
    assert obs.internal_error_count >= 1


def test_file_write_failure_does_not_fail_workflow(tmp_path, langsmith_capture):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    settings = ls_settings(blocker / "obs.jsonl")  # parent is a file -> every write fails
    obs, _ = both_sinks(settings, blocker / "obs.jsonl")
    with obs.workflow("wf", request_id="REQ-3"):
        with obs.agent("a") as a:
            a.annotate(ok=True)
    obs.flush()
    file_sink = obs.sink("file")
    assert file_sink.write_failures >= 1
    obs.shutdown()
    assert {r["name"] for r in langsmith_capture["runs"]().values()} == {"wf", "a"}  # other sink unaffected


def test_serialization_failure_is_contained(make_obs, read):
    class Evil:
        def model_dump(self):
            raise RuntimeError("cannot dump")

        def __repr__(self):
            raise RuntimeError("cannot repr")
    obs = make_obs(capture_outputs=True, capture_inputs=True)
    with obs.agent("a", inputs=Evil()) as a:
        a.set_outputs({"x": Evil(), "y": float("nan"), "z": b"\x00\x01"})
    ev = read(obs)
    assert ev[-1]["event_type"] == "agent_completed"
    assert ev[-1]["outputs"] == {"x": "<unserializable Evil>", "y": "nan", "z": "<bytes len=2>"}


# ---- 22. concurrency ---------------------------------------------------------------------------------

def test_concurrent_writes_remain_valid_jsonl(make_obs, log_path):
    obs = make_obs(capture_messages=True)
    n_threads, per_thread = 16, 40

    def worker(i):
        for j in range(per_thread):
            with obs.workflow("wf", request_id=f"REQ-{i}-{j}"):
                with obs.llm_call(component="c", operation="o") as call:
                    call.set_messages([("human", "x" * 3000 + f"{i}-{j}")])
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    obs.shutdown()
    valid, invalid = validate_file(log_path)
    assert invalid == [] and valid == n_threads * per_thread * 4
    assert obs.sink("file").dropped_events == 0


def test_bounded_queue_drops_instead_of_blocking(tmp_path):
    sink = JsonlFileSink(tmp_path / "o.jsonl", queue_size=10)
    sink._queue.put_nowait  # noqa: B018 - sanity
    obs = ObservabilityManager(ObservabilitySettings(log_file=tmp_path / "o.jsonl", langsmith_enabled=False), sinks=[sink])
    block = threading.Event()
    real_write = sink._write
    sink._write = lambda lines: (block.wait(5), real_write(lines))  # stall the writer thread
    for _ in range(50):
        with obs.agent("a"):
            pass
    block.set()
    obs.shutdown()
    assert sink.dropped_events > 0 and validate_file(tmp_path / "o.jsonl")[1] == []


# ---- 23-24. redaction before persistence / secrets ----------------------------------------------------

def test_redaction_and_secrets_before_persistence(log_path, langsmith_capture, monkeypatch):
    monkeypatch.setenv("PAYMENTS_API_TOKEN", "tok-live-9f8e7d6c5b4a")
    s = ls_settings(log_path, capture_inputs=True, capture_outputs=True, capture_messages=True)
    redactor = Redactor.from_settings(s, secrets=["gmail-app-pass-xyz"])
    obs, _ = both_sinks(s, log_path, redactor)
    model = GenericFakeChatModel(messages=iter([AIMessage("reply to ceo@corp.com with tok-live-9f8e7d6c5b4a")]))
    with obs.workflow("wf", request_id="REQ-4", inputs={"password": "pw-123456", "q": "Authorization: Bearer abcdef123456"}):
        with obs.agent("a", inputs={"note": "gmail-app-pass-xyz"}):
            with obs.llm_call(component="a", operation="o") as call:
                call.set_response(model.invoke([("system", f"key {LS_KEY}"), ("human", "mail ceo@corp.com")]))
            with obs.tool_call("t", inputs={"headers": {"Cookie": "sid=abc"}}) as t:
                t.set_outputs({"api_key": "k-123456", "text": "tok-live-9f8e7d6c5b4a"})
    obs.shutdown()
    local = log_path.read_text(encoding="utf-8")
    remote = json.dumps([langsmith_capture["posts"], langsmith_capture["patches"]], default=str)
    for secret in ("tok-live-9f8e7d6c5b4a", "gmail-app-pass-xyz", LS_KEY, "pw-123456", "abcdef123456", "sid=abc",
                   "k-123456", "ceo@corp.com"):
        assert secret not in local, secret
        assert secret not in remote, secret
    assert "[REDACTED]" in local and "[REDACTED_EMAIL]" in remote


def test_capture_disabled_never_writes_payloads(log_path, langsmith_capture):
    obs, _ = both_sinks(ls_settings(log_path), log_path)  # capture flags default to False
    prompt, answer = "CONFIDENTIAL-PROMPT-TEXT", "CONFIDENTIAL-ANSWER-TEXT"
    model = GenericFakeChatModel(messages=iter([AIMessage(answer)]))
    with obs.workflow("wf", inputs={"q": prompt}):
        with obs.agent("a", inputs=prompt) as a:
            with obs.llm_call(component="a", operation="o", messages=[("human", prompt)]) as call:
                call.set_response(model.invoke([("human", prompt)]))
                call.set_output({"parsed": answer})
            a.set_outputs(answer)
        with obs.tool_call("t", inputs={"q": prompt}) as t:
            t.set_outputs(answer)
    obs.shutdown()
    local = log_path.read_text(encoding="utf-8")
    remote = json.dumps([langsmith_capture["posts"], langsmith_capture["patches"]], default=str)
    for text in (prompt, answer):
        assert text not in local and text not in remote
    llm_done = next(e for e in read_events(log_path) if e["event_type"] == "llm_call_completed")
    assert llm_done["input_captured"] is False and llm_done["output_captured"] is False


def test_capture_enabled_writes_redacted_payloads(make_obs, read):
    obs = make_obs(capture_messages=True, capture_outputs=True, max_payload_chars=100)
    with obs.llm_call(component="c", operation="o") as call:
        call.set_messages([("system", "rules"), ("human", "y" * 500)])
        call.set_output({"answer": "ok"})
    done = read(obs)[-1]
    assert done["messages"][0] == {"role": "system", "content": "rules"}
    assert done["messages"][1]["content"].startswith("y" * 100) and "truncated 400 chars" in done["messages"][1]["content"]
    assert done["outputs"] == {"answer": "ok"} and done["input_captured"] and done["output_captured"]


# ---- step events, explicit API, integrations -------------------------------------------------------

def test_llm_step_events_are_opt_in(make_obs, read, log_path):
    obs = make_obs(llm_step_events=True)
    with obs.llm_call(component="c", operation="o") as call:
        call.set_messages([("human", "q")])
        call.set_response(AIMessage("a"))
        call.set_parsed(False, ValueError("bad json"))
    types = [e["event_type"] for e in read(obs)]
    assert types == ["llm_call_started", "prompt_prepared", "response_received", "response_parsed", "llm_call_completed"]


def test_explicit_start_end_api(make_obs, read):
    obs = make_obs()
    wf = obs.start_trace("wf", request_id="REQ-5")
    ag = obs.start_agent("a")
    llm = obs.log_llm_start(component="a", operation="o", provider="p", model="m")
    obs.log_llm_end(llm, response={"usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    tool = obs.log_tool_start("t", connector="X")
    obs.log_tool_error(tool, RuntimeError("down"))
    obs.log_retry_started(component="a", operation="t", retry_number=1, reason="source_error")
    obs.log_retry_completed(component="a", operation="t", retry_number=1, outcome="success")
    obs.end_agent(ag)
    obs.end_trace(wf)
    ev = read(obs)
    assert [e["event_type"] for e in ev] == [
        "workflow_started", "agent_started", "llm_call_started", "llm_call_completed", "tool_call_started",
        "tool_call_failed", "retry_started", "retry_completed", "agent_completed", "workflow_completed"]
    assert {e["request_id"] for e in ev} == {"REQ-5"} and ev[3]["input_tokens"] == 3
    assert obs.current_span() is None


def test_langgraph_integration(make_obs, read):
    obs = make_obs()
    seen_config = {}

    def plumbing(state):
        return {"n": state["n"] + 1}

    def llm_step(state, config):
        seen_config.update(config.get("metadata", {}))
        with obs.llm_call(component="thinker", operation="think") as call:
            call.set_response(usage_model().invoke("x"))
        return {"n": state["n"] * 10}

    from typing import TypedDict

    class S(TypedDict):
        request_id: str
        n: int
    g = StateGraph(S)
    g.add_node("plumbing", plumbing)
    g.add_node("thinker", observe_node("thinker_agent", manager=obs)(llm_step))
    g.add_edge(START, "plumbing")
    g.add_edge("plumbing", "thinker")
    g.add_edge("thinker", END)
    graph = g.compile()
    with obs.workflow("graph_wf", request_id="REQ-6") as wf:
        out = graph.invoke({"request_id": "REQ-6", "n": 1}, config=graph_config(obs, run_name="orchestrator"))
    assert out["n"] == 20 and seen_config["request_id"] == "REQ-6" and seen_config["observability_trace_id"] == wf.trace_id
    ev = read(obs)
    names = [(e["event_type"], e["name"]) for e in ev]
    assert ("agent_started", "thinker_agent") in names and not any(n == "plumbing" for _, n in names)
    llm_done = next(e for e in ev if e["event_type"] == "llm_call_completed")
    agent_start = next(e for e in ev if e["event_type"] == "agent_started")
    assert llm_done["parent_run_id"] == agent_start["run_id"] and llm_done["total_tokens"] == 7
    assert agent_start["request_id"] == "REQ-6"


def test_generic_llm_helpers_and_async_decorator(make_obs, read):
    obs = make_obs()

    class FakeSdkResponse:
        usage = {"input_tokens": 9, "output_tokens": 3}
        content = "done"

    @observed_llm(component="gen", operation="complete", provider="anthropic", model="x", manager=obs,
                  messages_arg="messages")
    def complete(messages):
        return FakeSdkResponse()

    complete([{"role": "user", "content": "hi"}])
    call_llm(lambda: FakeSdkResponse(), component="gen", operation="direct", manager=obs)

    @obs.observe("agent", name="async_agent")
    async def run():
        return 42
    import asyncio
    assert asyncio.run(run()) == 42
    ev = read(obs)
    done = [e for e in ev if e["event_type"] == "llm_call_completed"]
    assert [(e["operation"], e["input_tokens"], e["output_tokens"]) for e in done] == [("complete", 9, 3), ("direct", 9, 3)]
    assert any(e["name"] == "async_agent" and e["event_type"] == "agent_completed" for e in ev)


def test_query_resolves_linked_traces(make_obs, log_path):
    obs = make_obs()
    with obs.workflow("analysis") as analysis:
        with obs.llm_call(component="c", operation="understand"):
            pass
    with obs.workflow("intake") as intake:
        obs.bind(request_id="REQ-9")
        obs.link_trace(analysis.trace_id, request_id="REQ-9", reason="reused_cached_analysis")
    with obs.workflow("other", request_id="REQ-OTHER"):
        pass
    obs.shutdown()
    ev = read_events(log_path, request_id="REQ-9")
    assert {e["trace_id"] for e in ev} == {analysis.trace_id, intake.trace_id}
    assert any(e["event_type"] == "llm_call_completed" for e in ev)  # LLM activity of the linked analysis trace


@pytest.mark.parametrize("bad", ["not json", '{"unterminated": '])
def test_validate_file_reports_invalid_lines(tmp_path, bad):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n' + bad + "\n")
    assert validate_file(p) == (1, [2])

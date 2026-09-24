# LLM Observability Module

A reusable, framework-agnostic observability layer for LLM applications. Application code calls one generic API
(`workflow`, `agent`, `llm_call`, `tool_call`, `retry`, `log_*`). The module sends normalized, redacted events to:

| Sink | Purpose |
|---|---|
| **LangSmith** (remote) | Trace visualization and hierarchy, LLM debugging, token/latency inspection, search/filter, production investigation |
| **Local JSONL** (`logs/llm_observability.jsonl`) | Portable audit/debug record, offline troubleshooting, machine-readable history, correlation by request / trace id |

Both sinks receive the same normalized event information. Neither replaces the other.

The module contains **no application/business logic**. It depends only on `pydantic` / `pydantic-settings`.
LangSmith, LangChain and LangGraph are optional.

```text
LLM application (agents, orchestrator, tools)
        │   obs.workflow / obs.agent / obs.llm_call / obs.tool_call / obs.retry / obs.log_*
        ▼
ObservabilityManager ── correlation ids (contextvars) ── capture policy ── Redactor
        │
        ├──► LangSmithSink   (adapters/langsmith_adapter.py)  langsmith.trace / tracing_context, shared Client
        └──► JsonlFileSink   (adapters/file_adapter.py)       bounded queue → single writer thread → one file

integrations/langchain.py  – LangChain callback hook (usage, provider run ids) – no pipeline changes
integrations/langgraph.py  – graph_config() correlation metadata, observe_node() for agent nodes
integrations/llm.py        – call_llm() / @observed_llm for any SDK (OpenAI, Anthropic, Groq, HTTP, ...)
```

## Layout

```text
observability/
  __init__.py          public API
  config.py            ObservabilitySettings (Pydantic Settings, env-driven)
  enums.py             EventType, RunType, Status, UsageSource
  models.py            ObservabilityEvent (one JSONL line), TokenUsage
  context.py           Span / TraceState + contextvars propagation
  manager.py           ObservabilityManager, handles, configure/get_observability
  interfaces.py        ObservabilitySink (implement to add a backend)
  redaction.py         Redactor (central masking)
  serializers.py       bounded, never-raising JSON conversion
  metrics.py           usage extraction, optional estimation and cost
  query.py             offline querying / validation of the JSONL log (also a CLI)
  adapters/            langsmith_adapter.py, file_adapter.py
  integrations/        langchain.py, langgraph.py, llm.py
  tests/               unit + integration tests (no host application needed)
```

## Installation

It ships as a top-level package in this repo (`backend/observability`). To reuse it elsewhere:

```bash
pip install ./backend/observability                  # core (pydantic, pydantic-settings)
pip install "./backend/observability[all]"           # + langsmith, langchain-core, langgraph
```

You can also copy the directory into another project as the `observability` package.

## Environment variables

All configuration comes from the environment, or from a `.env` passed as `ObservabilitySettings.load(env_file)`.
Defaults are safe: no payload capture, redaction on, and nothing sent remotely unless LangSmith is explicitly enabled and a key is present.

| Variable | Default | Meaning |
|---|---|---|
| `OBSERVABILITY_ENABLED` | `true` | Master switch. `false` → every call is a cheap no-op. |
| `OBSERVABILITY_ENVIRONMENT` | `development` | Written on every event. |
| `OBSERVABILITY_SERVICE_NAME` | – | Written on every event. |
| `OBSERVABILITY_FAIL_OPEN` | `true` | Telemetry failures never raise. `false` = strict mode for dev/tests. |
| `LANGSMITH_ENABLED` | `true` | Enables the LangSmith adapter (still needs the two below). |
| `LANGSMITH_TRACING` | `false` | LangSmith SDK switch (`LANGCHAIN_TRACING_V2` accepted). |
| `LANGSMITH_API_KEY` | – | Required for remote tracing (`LANGCHAIN_API_KEY` accepted). Never logged. |
| `LANGSMITH_PROJECT` | SDK default | Target project. |
| `LANGSMITH_ENDPOINT` | SDK default | Only for self-hosted / regional endpoints. |
| `OBSERVABILITY_LOG_FILE_ENABLED` | `true` | Enables the local JSONL adapter. |
| `OBSERVABILITY_LOG_FILE` | `logs/llm_observability.jsonl` | The single log file. Relative paths resolve against `base_dir` (or the CWD). |
| `OBSERVABILITY_LOG_ROTATION_ENABLED` | `false` | Size-based bounded rotation (see below). |
| `OBSERVABILITY_LOG_MAX_BYTES` / `OBSERVABILITY_LOG_BACKUP_COUNT` | `52428800` / `5` | Rotation limits. |
| `OBSERVABILITY_QUEUE_SIZE` | `10000` | Bounded writer queue. When full, events are dropped and counted; the app is never blocked. |
| `OBSERVABILITY_CAPTURE_INPUTS` | `false` | Span inputs (tool args, agent inputs). |
| `OBSERVABILITY_CAPTURE_OUTPUTS` | `false` | Model responses, structured output, tool results. |
| `OBSERVABILITY_CAPTURE_MESSAGES` | `false` | LLM prompt messages (system / user / tool). |
| `OBSERVABILITY_MAX_PAYLOAD_CHARS` | `4000` | Per-string truncation of captured payloads. |
| `OBSERVABILITY_LLM_STEP_EVENTS` | `false` | Also emit `prompt_prepared` / `response_received` / `response_parsed`. |
| `OBSERVABILITY_REDACTION_ENABLED` | `true` | Optional redaction rules (credential masking is always on). |
| `OBSERVABILITY_REDACT_EMAILS` | `true` | Mask e-mail addresses. |
| `OBSERVABILITY_REDACT_FINANCIAL_IDENTIFIERS` | `false` | Mask IBAN / card / account-number patterns and bank/payment keys. |
| `OBSERVABILITY_REDACT_FIELDS` | – | Extra sensitive key names (comma-separated or JSON list). |
| `OBSERVABILITY_REDACT_PATTERNS` | – | Extra regexes (JSON list). |
| `OBSERVABILITY_TOKEN_ESTIMATION_ENABLED` | `false` | Estimate tokens when the provider reports none (`usage_source="estimated"`). |
| `OBSERVABILITY_COST_TRACKING_ENABLED` | `false` | Compute `estimated_cost` from **your** pricing (none is built in). |
| `OBSERVABILITY_INPUT_COST_PER_1K_TOKENS` / `OBSERVABILITY_OUTPUT_COST_PER_1K_TOKENS` | – | Default prices. |
| `OBSERVABILITY_MODEL_PRICING` | – | JSON: `{"model": {"input_cost_per_1k_tokens": 0.1, "output_cost_per_1k_tokens": 0.4}}` |
| `OBSERVABILITY_COST_CURRENCY` | `USD` | `cost_currency` on events. |

Invalid values never crash the host. `ObservabilitySettings.load()` logs a warning, falls back to safe defaults, and emits an
`observability_error` event.

## Simple Python example

```python
from observability import get_observability

obs = get_observability()                      # configured from the environment on first use

with obs.workflow(name="audit_request", request_id=request_id):
    with obs.agent(name="query_understanding", request_id=request_id) as agent:
        with obs.llm_call(component="query_understanding", operation="structured_query",
                          provider="openai", model=model_name, request_id=request_id) as call:
            call.set_messages(messages)        # logged only if OBSERVABILITY_CAPTURE_MESSAGES=true
            response = llm.invoke(messages)
            call.set_response(response)        # usage/model extracted when the provider reports them
        agent.annotate(llm_used=True)
```

If an exception escapes a block, the span is recorded as `*_failed` (error type, sanitized message, latency). The
exception is then re-raised unchanged. Other helpers:

```python
obs.log_fallback_started(component="qa", fallback_type="rules_based", reason="llm_disabled")
obs.log_fallback_completed(component="qa", fallback_type="rules_based", reason="llm_disabled")

with obs.retry(component="retriever", operation="search", retry_number=1, reason="source_error",
               previous_error_type="HTTP_503") as r:
    result = search()                          # tool spans started here get retry_count=1
    r.set_outcome("success" if result.ok else "failed")

with obs.tool_call("search", connector="CRM") as tool:
    tool.set_result(ok, error_type="HTTP_503" if not ok else None, found=bool(rows), record_count=len(rows))

obs.bind(request_id="REQ-1001")                # attach a request id to the current trace once it is known
obs.link_trace(earlier_trace_id, request_id="REQ-1001", reason="reused_cached_analysis")
obs.log_validation("schema_check", outcome="passed")
obs.log_error(exc, component="qa")
```

There is also an explicit API for code that cannot use `with`: `start_trace/end_trace`, `start_agent/end_agent`,
`log_llm_start/log_llm_end/log_llm_error`, `log_tool_start/log_tool_end/log_tool_error`,
`log_retry_started/log_retry_completed`. A decorator form is `@obs.observe("agent", name=...)` (sync and async).

## FastAPI integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from observability import configure_observability, get_observability, ObservabilitySettings

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_observability(ObservabilitySettings.load(".env"), base_dir=BASE_DIR,
                            secrets=[settings.db_password])   # app secrets not in os.environ
    yield
    get_observability().shutdown()                          # flush file + pending LangSmith batches

app = FastAPI(lifespan=lifespan)

@app.post("/ask")
def ask(body: Ask):
    obs = get_observability()
    with obs.workflow("ask", request_id=body.request_id):
        ...
```

Correlation ids live in `contextvars`, so each request, thread-pool call or asyncio task has its own context.
Concurrent requests never share ids, and no lock is held around application code.

## LangChain integration

Nothing needs to change in the chain. Inside an `llm_call` block, the LangChain callback hook (registered with
`register_configure_hook`) captures provider token usage, the model name and the LangChain run ids:

```python
with obs.agent("query_understanding"):
    with obs.llm_call(component="query_understanding", operation="structured_query",
                      provider="groq", model="openai/gpt-oss-120b") as call:
        result = chain.invoke(inputs)          # usage recorded automatically via callbacks
        call.set_output(result)
```

When LangSmith is active, LangChain's own tracer records the model run as a child of the current span. The adapter
then does **not** create a second LLM run, so there are no duplicates. Optionally pass
`config=call.langchain_config()` to add correlation metadata/tags to the LangChain runs.

## LangGraph integration

```python
from observability.integrations.langgraph import graph_config, observe_node

g.add_node("retrieve", observe_node("retrieval_agent")(retrieve_node))   # meaningful agent steps only
...
with obs.workflow("audit_workflow", request_id=rid):
    graph.invoke(state, config=graph_config(obs, run_name="orchestrator"))
```

`graph_config` puts `request_id` / `observability_trace_id` into `config["metadata"]`, and LangGraph propagates it to every
node run in LangSmith. Leave deterministic plumbing nodes unwrapped to keep traces readable.

## Generic LLM integration (no LangChain)

```python
from observability.integrations.llm import call_llm, observed_llm

resp = call_llm(client.chat.completions.create, model="gpt-x", messages=msgs,
                component="summarizer", operation="summarize", provider="openai")

@observed_llm(component="summarizer", operation="summarize", provider="anthropic", model="x", messages_arg="messages")
def summarize(messages):
    return anthropic_client.messages.create(model="x", messages=messages, max_tokens=500)
```

Usage is read from `.usage` (OpenAI `prompt_tokens`/`completion_tokens`, Anthropic `input_tokens`/`output_tokens`, cache
and reasoning details) or from `.usage_metadata`. For other SDKs, call `call.set_usage(input_tokens=..., output_tokens=...)`.
Token counts are **never invented**. Unreported usage is `null`, and estimates are labelled `usage_source="estimated"`.

## Local JSONL

One append-only file, with one JSON object per line. It is never split per request, agent, model, day or user.

```json
{"event_id":"…","timestamp":"2026-09-24T12:35:10.122Z","event_type":"llm_call_completed","run_type":"llm",
 "name":"query_understanding_agent.structured_query_generation","trace_id":"…","run_id":"…","parent_run_id":"…",
 "request_id":"AUD-2026-1001","component":"query_understanding_agent","operation":"structured_query_generation",
 "provider":"groq","model":"openai/gpt-oss-120b","status":"success","latency_ms":842.1,"input_tokens":812,
 "output_tokens":236,"total_tokens":1048,"usage_source":"provider","retry_count":0,"input_captured":false,
 "output_captured":false,"environment":"development"}
```

- Core keys are present on every line, `null` when not applicable: `event_id, timestamp, event_type, run_type, name,
  trace_id, run_id, parent_run_id, request_id, component, operation, provider, model, status, latency_ms, error_type,
  error_message, retry_count, environment`.
- LLM events also always carry `input_tokens, output_tokens, total_tokens, usage_source, input_captured, output_captured`.
- Other fields (`cached_tokens`, `reasoning_tokens`, `fallback_type`, `reason`, `retry_number`, `tool_name`,
  `connector`, `parent_llm_run_id`, `linked_trace_id`, `attributes`, payloads, ...) appear only when they have a value.
- Hierarchy: `request_id → trace_id (= root run id = LangSmith trace id) → run_id / parent_run_id`. Tool events
  requested by an LLM carry `parent_llm_run_id`.

Concurrency: application threads only enqueue on a **bounded** queue. One writer thread appends whole lines, so the
file cannot be corrupted by concurrent FastAPI requests.

Rotation (`OBSERVABILITY_LOG_ROTATION_ENABLED=true`): before the active file would exceed
`OBSERVABILITY_LOG_MAX_BYTES`, it is renamed to `<file>.1` (older backups shift to `.2`, ...). A new `<file>` is then
started. At most `OBSERVABILITY_LOG_BACKUP_COUNT` backups are kept, and the oldest is deleted. The logical destination is always
the configured path.

Querying:

```bash
python -m observability.query logs/llm_observability.jsonl --request-id AUD-2026-1001
python -m observability.query logs/llm_observability.jsonl --request-id AUD-2026-1001 --event-type llm_call_completed
python -m observability.query logs/llm_observability.jsonl --validate        # every line valid JSON?
```

`--request-id` includes traces bound or linked to the request (`correlation_linked`). Work done before the application
knew its request id is therefore included.

## LangSmith configuration

```bash
LANGSMITH_ENABLED=true
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...          # from a secrets manager; never commit
LANGSMITH_PROJECT=my-project
```

- The adapter uses the current SDK primitives: `langsmith.trace(...)` for workflow/agent/tool spans, and
  `langsmith.tracing_context(enabled=True, client=..., project_name=...)` around root spans, so tracing follows this
  module's settings rather than global env state. Post-hoc `RunTree.create_child(...).post()` is used only for LLM calls
  not already traced by LangChain.
- The local `run_id` is used as the LangSmith run id, and the local `trace_id` equals the LangSmith trace id.
- Metadata on runs: `request_id`, `component`, `operation`, `provider`, `model`, `status`, `latency_ms`, and `attr.*`.
  Filter in LangSmith with `metadata_key = "request_id"`.
- Retries, fallbacks and validations become run events. Fallbacks also add `llm_fallback_type` metadata and an
  `llm_fallback` tag, and retries add a `retry` tag.
- One shared `Client` per process. The SDK batches in a background thread, so the application never waits on LangSmith.
- The client's `hide_inputs` / `hide_outputs` hooks apply the capture policy and the redactor to **every** run it sends,
  including runs generated by LangChain/LangGraph. With output capture off, LLM runs keep token usage and model name,
  but all content is stripped.

## Redaction

Redaction runs **before** an event reaches any sink. It is applied in `ObservabilityManager._build`, and in the LangSmith
client hooks for framework-generated runs.

- **Credential masking (always on):** values under sensitive keys (`password`, `secret`, `api_key`, `authorization`, `cookie`,
  `*_token`, `client_secret`, `private_key`, `credentials`, ...), `Authorization:` / `Cookie:` headers, `Bearer`/`Basic`
  tokens, `key=value` secrets, URL credentials, well-known key formats (OpenAI/Anthropic `sk-`, Groq `gsk_`, LangSmith
  `lsv2_`, GitHub, Slack, AWS, Google), JWTs and PEM private keys.
- **Known secret values:** the exact values of environment variables whose names look secret (`*KEY*`, `*SECRET*`,
  `*TOKEN*`, `*PASSWORD*`, ...), the LangSmith API key, and anything passed via `secrets=[...]` or `redactor.register_secret()`.
  Use this for secrets loaded from `.env` files that are not in `os.environ`.
- **Optional (on by default):** e-mail addresses. **Optional (opt-in):** financial identifiers
  (`OBSERVABILITY_REDACT_FINANCIAL_IDENTIFIERS=true`).
- **Organization-specific:** `OBSERVABILITY_REDACT_FIELDS=vendor_bank_ref,tax_id`,
  `OBSERVABILITY_REDACT_PATTERNS=["\\bEMP-\\d{4}\\b"]`, or `redactor.add_field()` / `redactor.add_pattern()`.

`input_tokens` / `max_tokens` style keys are deliberately *not* treated as secrets.

## Disabling observability

- Everything: `OBSERVABILITY_ENABLED=false`. Context managers yield a no-op handle, and nothing is written or sent.
- Remote only: `LANGSMITH_ENABLED=false` or `LANGSMITH_TRACING=false`.
- Local file only: `OBSERVABILITY_LOG_FILE_ENABLED=false`.

## Failure behaviour (fail-open)

Every sink call, handle method, serialization and configuration step is isolated. Suppose LangSmith is unreachable,
the log file is unwritable, an object cannot be serialized, or the configuration is invalid. In each case the
application continues. A rate-limited warning is logged on the `observability` logger. An `observability_error` event
is written to the *healthy* sinks. `ObservabilityManager.internal_error_count` increases. A full writer queue drops
events (`JsonlFileSink.dropped_events`) instead of blocking. Set `OBSERVABILITY_FAIL_OPEN=false` to make these errors
raise in development/tests.

## Adding a backend

Subclass `observability.interfaces.ObservabilitySink`. Implement `emit(event, span)`, and optionally
`start_span` / `end_span` / `flush` / `shutdown`. Pass it with `configure_observability(sinks=[...])`. Sinks only ever
receive redacted events.

## Troubleshooting

| Symptom | Check |
|---|---|
| No LangSmith traces | `LANGSMITH_ENABLED`, `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` must all be set. Look for the warning "LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is not set". Check `LANGSMITH_ENDPOINT` for regional deployments. Call `get_observability().flush()` before process exit in scripts. |
| No local file | `OBSERVABILITY_LOG_FILE` path / permissions. `observability_error` warnings on the `observability` logger. `obs.sink("file").write_failures`. |
| Missing events | `obs.sink("file").dropped_events` (raise `OBSERVABILITY_QUEUE_SIZE`). Call `flush()` before reading the file. |
| Tokens are `null` | The provider did not report usage, and the module never invents it. Use `call.set_usage(...)`, or enable estimation (clearly labelled). |
| Prompts not visible | Capture is off by default. Enable `OBSERVABILITY_CAPTURE_MESSAGES` / `_OUTPUTS` (development only). |
| Early events lack `request_id` | They ran before the id existed. `bind()` / `link_trace()` correlate the trace, and `query --request-id` resolves it. |

## Testing

```bash
cd backend
python -m pytest observability/tests            # module unit + integration tests (no host app needed)
python -m pytest                                # everything, incl. host-application observability tests
```

LangSmith is tested at the SDK boundary: `langsmith.Client._create_run` / `_update_run` are intercepted, so the tests
check the real runs the SDK would send, after its masking hooks ran. No network access is needed.

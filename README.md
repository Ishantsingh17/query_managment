# Audit Evidence Platform

End-to-end implementation of the Audit Evidence Platform described in `01_PRD` … `06_Implementation_Plan`, with the web UI built to match `UI_SCREENS/`.

```
backend/   Python 3.13 · FastAPI · SQLAlchemy · SQLite · LangGraph orchestrator · MCP gateway · mock source APIs
frontend/  React 19 · Vite · TypeScript · hand-built CSS design system (matches UI_SCREENS 01–12)
```

## Quick start (Windows / macOS / Linux)

```bash
# 1. Backend
cd backend
python -m venv .venv
```

Activate it — Windows (PowerShell): `.\.venv\Scripts\Activate.ps1` — macOS/Linux: `source .venv/bin/activate`.
Every `pip`/`python` command below assumes it's active in that terminal; a fresh venv is required because the
project's dependencies (e.g. `langchain-groq`, only needed once `AEP_LLM_PROVIDER=groq`) are declared in
`requirements.txt`, not preinstalled anywhere.

```bash
pip install -r requirements.txt
copy .env.example .env                 # macOS/Linux: cp .env.example .env — then fill in your keys
python -m app.seed_demo --reset        # optional: demo data pushed through the real workflow
python -m uvicorn app.main:app --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                            # http://localhost:5173  (proxies /api to :8000)
```

On Windows you can run `start.ps1` from the repo root to launch both — it expects `backend/.venv` to already
exist (run the backend setup above at least once first) and activates it for you.

### Demo accounts (password `Password@123`)

| Role | Email | Lands on |
|---|---|---|
| Auditor | sarah.mitchell@company.com | Dashboard |
| Human Validator | david.okafor@company.com | Evidence Review Queue |
| Final Approver (SME) | priya.raman@company.com | Final Approval Queue |

## Screen map

| Screen | Route | Role |
|---|---|---|
| 01 Login | `/login` | all |
| 02 Auditor Dashboard | `/dashboard` | Auditor (SME gets a portfolio view) |
| 03 Create Request | `/requests/new` | Auditor |
| 04 Request Detail | `/requests/:id` | all |
| 05 Evidence Review Queue | `/queue` | Validator |
| 06 Validation Detail | `/queue/:id`, `/validation/requests/:id` | Validator |
| 07 Final Approval Queue | `/approvals` | SME |
| 08 Evidence Review Package | `/approvals/:id`, `/approvals/requests/:id` | SME |
| 09 Approve / Reject dialogs | on 08 | SME |
| 10 Final Response Package | `/requests/:id/package` (`/final`) | Auditor |
| 11 Completed Requests | `/completed` | all |
| 12 Status drawer | click a Request ID on the dashboard, or **View Timeline** | all |

Also: Requests grid, Reports, Settings (source-system status), Help Center, global search (⌘K / Ctrl+K), notification bell.

## Stakeholder configuration (authoritative)

Loaded from `backend/app/db/stakeholder_config.py` into SQLite on startup (`python -m app.db.seed_config` re-applies it and removes any row that isn't in it):

| Query Type | Evidence required (Requirement Catalog) | Retrieval parameters (from the registry keys) |
|---|---|---|
| Trade Payables Balance Confirmation | Vendor-wise payable balance, Ageing, Signed confirmation letter, APTB ledger extract, Vendor contact details | Vendor ID |
| Balance Confirmation – Alternate Testing | Invoice, PO, GRN/SES | Invoice Number (or Payment Document Number) |
| Payment Report / Payment Testing | Payment report, Invoice, PO, GRN/SES, Approval, Payment advice / UTR, Accounting entries | Payment Document Number |
| Bank Portal / Payment Process Walkthrough | Signatory email approval, IPAMS approval, Board Resolution limits | Payment Document Number, Fiscal Year |

- `requirement_catalog` (exact 4 fields) says **what** is required. `evidence_source_registry` (exact 7 fields) says **where and how** to retrieve it. The stakeholder automation text and classification keywords live in a separate `query_type_definitions` table.
- Search / Retrieval Keys grammar: `A / B` = either key; `A, B` = both keys; `PO Number [from INVOICE]` = may come from the request, or from the retrieved invoice. Code only derives a key where the registry states it this way.
- **Source systems:** only Invoice→GROSS, PO→ARIBA, GRN/SES→GESS and Approval→IPAMS are documented, in the App Flow. The other registry rows are marked as development placeholders pending stakeholder confirmation; change them in the config file, not in code.

## Architecture (backend)

```
API (FastAPI, role checks in backend)
 └─ Orchestrator (LangGraph state graph, app/orchestrator/graph.py)
     understand → classify → resolve_requirements → resolve_sources → plan → retrieve → process → validate
        ├─ complete   → Evidence Review Package → notify SME
        └─ incomplete → REWORK_REQUIRED → Validator: retry | manual upload | accept not required → continue
     SME approve → Final Response Package (approved evidence only, sealed with SHA-256) → notify auditor → COMPLETED
     SME reject  → REJECTED → REWORK_REQUIRED
```

| Component | Location |
|---|---|
| Config tables (exact 4- and 7-field schemas) + seed | `app/db/models.py`, `app/db/seed_config.py` (validated at startup) |
| Request DB (7 agreed tables + `users`, `request_events`) | `app/db/models.py` → `storage/db/audit_evidence.sqlite` |
| Query Understanding / Classification | `app/agents/query_understanding.py`, `classification.py` |
| LLM provider | `app/agents/llm.py` — `groq` (GROQ_API_KEY, `openai/gpt-oss-120b`), `langchain` (any init_chat_model string) or `rules` |
| Agentic Retrieval Agent (LLM tool-calling over MCP, guard-railed) | `app/agents/llm_retrieval_agent.py` |
| Registry resolution + Retrieval Planning | `app/registry/resolution.py`, `app/agents/retrieval_planning.py` |
| Retrieval Agent (key dependencies, alternative / corroborating sources, retries) | `app/agents/retrieval_agent.py` |
| MCP gateway + 9 source connectors | `app/mcp/` — also exposed as JSON-RPC `POST /mcp` (`tools/list`, `tools/call`) |
| Mock source APIs (Oracle, GRS, VMS, GESS, LMS, ARIBA, GPS, GROSS, IPAMS) | `app/mock_sources/` → `storage/db/source_mocks.sqlite`, `/mock-api/{source}/{object}` |
| Extraction / Normalization / Canonical Evidence / Staging | `app/evidence/` → `storage/evidence_staging/<request_id>/{original,normalized,manual_uploads}` |
| Completeness validation | `app/validation/engine.py` (pluggable extra rules) |
| Packages | `app/packages/builder.py` → `storage/packages/<request_id>/` |
| Gmail notifications | `app/notifications/service.py` |

### Swapping to real source APIs (plan step 14)
Point `AEP_SOURCE_API_BASE_URL` at the real gateway and adjust each connector's `base_path` / `auth_headers()` in `app/mcp/connectors.py`. The MCP tool contract, Retrieval Agent and Registry stay unchanged; registry rows carry the endpoint path (`… - GET /invoices`).

### LLM agents (Groq)
With `GROQ_API_KEY` and `AEP_LLM_PROVIDER=groq` in `backend/.env`:
- **Query Understanding + Classification**: the LLM extracts identifiers and picks exactly one query type from the stakeholder Query Type Definitions, or flags ambiguity (enforced by the schema). Identifiers not literally present in the request are discarded. The rationale appears in the request's Activity trail.
- **Agentic Retrieval**: the LLM calls the `RetrieveEvidence` MCP tool, choosing call order, deriving keys from earlier results and falling back to alternative sources. Guardrails reject sources outside the retrieval plan, wrong key names, invented identifier values, early alternative calls, and repeated calls; there's also a step budget.
- **Fallbacks**: any LLM error falls back to the deterministic agents. The LLM runs once per **Analyse request** click; its result is reused when the request is submitted. The demo seeder always uses rules.
- Set `AEP_LLM_AGENTIC_RETRIEVAL=false` to keep LLM classification with deterministic retrieval.

### LLM observability
`backend/observability/` is a standalone, reusable package with no audit logic and no dependency on `app`. Agents call its generic API only. Events go to one local file, `backend/logs/llm_observability.jsonl`, and optionally to LangSmith (`LANGSMITH_TRACING=true` plus `LANGSMITH_API_KEY`). Each event covers one of: an LLM call (tokens, latency, errors), a rules-based or deterministic fallback, an agent step, an MCP tool call, a retry, or the validation result. All of them correlate by request id. Prompt and response capture is off by default, and redaction always runs first.
```
python -m observability.query logs/llm_observability.jsonl --request-id AUD-2026-1001   # from backend/
```
See [backend/observability/README.md](backend/observability/README.md) for configuration and for reusing it in other apps.

### Email notifications
Notifications go to the Human Validator (evidence missing, or SME rejection), the SME (review package ready) and the Auditor (final package approved); see the table below. Test any configuration with:
```
python -m app.notifications.test_email you@example.com
```
**Option A: Gmail SMTP + App Password** (`AEP_NOTIFICATION_PROVIDER=gmail`). Needs outbound TCP 465 or 587. These ports are blocked on the current corporate network.
1. On the sender Google account, turn on 2-Step Verification (myaccount.google.com → Security).
2. Create an App Password at myaccount.google.com/apppasswords and copy the 16 characters.
3. Set `AEP_GMAIL_APP_PASSWORD=...` and `AEP_NOTIFICATION_PROVIDER=gmail`.

**Option B: Gmail API over HTTPS** (`AEP_NOTIFICATION_PROVIDER=gmail_api`). Uses only port 443, so it works on this network.
1. console.cloud.google.com → create a project → APIs & Services → Library → enable **Gmail API**.
2. OAuth consent screen (Google Auth Platform): User type **External**, app name "Audit Evidence Platform", add the sender Gmail under **Test users**.
3. Clients → Create client → **Desktop app** → download the JSON.
4. `python -m app.notifications.gmail_oauth_setup C:\Users\you\Downloads\client_secret.json`. Sign in as the sender and allow "Send email". The script saves the credentials to `backend/.env` and switches the provider.
5. Restart the backend and run the test command.

While the OAuth app is in "Testing", Google expires refresh tokens after 7 days. Re-run step 4, or publish the app, for a long-lived token.

For both options, set `AEP_NOTIFICATION_RECIPIENT_OVERRIDE=<your inbox>`, because the demo users' `@company.com` addresses are fictional. Every delivery attempt is recorded in `notification_events` (SENT / LOGGED / FAILED) and shown under the notification bell. A failed send never blocks the workflow.

## Mock data scenarios

| Query | Scenario |
|---|---|
| Payment testing, doc `1900004533` | **A** complete, and **D** multi-source: 7 items from ORACLE, GROSS, ARIBA, GESS, IPAMS, GPS |
| Payment testing, doc `1900004521` | **B** approval missing → Rework Required → validator email → manual upload |
| Payment testing, doc `1900004552` | **C** GRN posted late → **Retry** retrieves it |
| Any request + `POST /mock-api/_admin/sources/GPS/availability?available=false` | **E** source outage → retryable, recovers after retry |
| Payment testing, doc `1900004560` | Invoice references a PO that ARIBA doesn't hold |
| Balance confirmation, vendor `1004821` / `1004877` | Complete / confirmation letter not received |
| Alternate testing, `INV-2026-08560` / `INV-2026-08533` | Complete (with SES) / PO and GRN missing |
| Walkthrough, doc `1900004533` + `FY2026` / doc `1900004521` + `FY2026` | Complete / IPAMS approval missing |

The late-GRN scenario (C) only works once after a reset: `python -m app.seed_demo --reset`, with the backend stopped.

## Conversational intake

Create Request is a conversation. The auditor describes the need, the platform shows its **Request Understanding** (Query Type, extracted parameters, evidence requested, required and missing parameters, status), and then:
- if everything is present, **Submit request** starts retrieval;
- if a mandatory parameter is missing, it asks for it (e.g. *"…but I need the Payment Document Number to continue"*) and re-checks once supplied;
- if the request matches more than one Query Type, the auditor picks one; if it matches none, it lists the supported types.

The API enforces the same rules: `POST /api/requests` returns 422 unless the understanding is READY.

## Email notifications and login-first links

| Event | Recipient | Link |
|---|---|---|
| Evidence missing / unclear, or SME rejection | Human Validator | `/login?next=/validation/requests/{id}` |
| Evidence Review Package ready | SME | `/login?next=/approvals/requests/{id}` |
| Final Response Package approved | Auditor | `/login?next=/requests/{id}/package` |

Every link lands on the common sign-in page. After sign-in, the backend checks `next` against the user's role and access to that request (`POST /api/auth/login`, `GET /api/auth/resolve-next`). Wrong-role, foreign or external targets go to the user's home instead.

For development, set `AEP_NOTIFY_VALIDATOR_EMAIL`, `AEP_NOTIFY_SME_EMAIL` and `AEP_NOTIFY_AUDITOR_EMAIL`; these take precedence over `AEP_NOTIFICATION_RECIPIENT_OVERRIDE`.

## Tests

```bash
cd backend && python -m pytest -q      # 108 tests: unit, connector contract, MCP, end-to-end + failure paths, observability
cd frontend && npm run build           # typecheck + production build
```

Covered: all four stakeholder Query Types; natural-language classification (identified, ambiguous, unsupported); Requirement Catalog and Registry lookups with exact schemas; missing-parameter and conversational follow-up; complete and missing retrieval; validator, SME and auditor emails; manual upload; retry; accept-not-required; SME approval and rejection; Final Response Package with approved evidence only; common-login and role-safe redirects; unauthorised access; duplicate requests; source outage; package-generation failure and regeneration; documented-dependency-only key derivation; LLM agents with guardrails and fallbacks.

# Automated Audit Evidence Retrieval — POC

Turns an auditor's natural-language request into a validated, reviewer-approved
evidence package.

```
Auditor → FastAPI → LangGraph Orchestrator → Query Understanding (Groq)
       → Requirement Catalog → Retrieval Agent → MCP Layer → SQLite DB-01…DB-04
       → Evidence Staging → Validation → Retry → Package → Reviewer
```

Local only. No authentication, no deployment, synthetic data throughout.

---

## Quick start

`backend\.venv`, `frontend\node_modules`, the mock databases and the documents
are **already set up**. To just run it, skip to *Run it* below.

> **Never run `python -m venv .venv` while the backend is running.** On Windows
> the live `python.exe` holds locks inside `.venv`, and recreating it mid-flight
> leaves a broken environment (a missing `pyvenv.cfg` and a stripped
> `Scripts\`). Stop the server first — see *If the venv breaks*.

### Run it

Two terminals, from the project root.

**Terminal 1 — backend**

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — frontend**

```powershell
cd frontend
npm run dev
```

Open <http://localhost:3000>. Check <http://127.0.0.1:8000/health> if anything
looks unwired.

### First-time setup (only if `.venv` is absent)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env

.\.venv\Scripts\python.exe scripts\seed_databases.py
.\.venv\Scripts\python.exe scripts\init_app_state.py
```

```powershell
cd frontend
npm install
```

### If the venv breaks

Symptom: `failed to locate pyvenv.cfg: The system cannot find the file specified.`

```powershell
# 1. Stop anything holding the environment or the ports
Get-Process python, node -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. Rebuild from scratch
cd backend
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The generated data (`databases\`, `mock_documents\`, `app_state.sqlite`) lives
outside `.venv` and survives this, so re-seeding is not required. To confirm the
rebuild: `.\.venv\Scripts\python.exe -m pytest` should report 30 passed.

To free the ports specifically:

```powershell
Get-NetTCPConnection -LocalPort 8000,3000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### The demo query

> Provide alternate testing documents for ABC Ltd, Invoice INV-12345.

Expected: UC-04 → evidence found across DB-01, DB-02, DB-04 → SES missing →
one retry finds it in DB-03 → validation COMPLETE → package → approve.

---

## Configuration

`backend/.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(empty)* | Leave blank to use the deterministic rule-based parser. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Verified against this account. Model availability is per-key — list yours with the Groq SDK (see TEST_INPUTS.md). Tool calling is required, which rules out the `qwen` and `groq/compound` models. |
| `MAX_RETRIES` | `2` | Bounds the retry loop. |
| `DEMO_STEP_DELAY_MS` | `700` | Paces stages so `DB-01 → DB-04` is visibly sequential. Set `0` for instant runs and tests. |

`NEXT_PUBLIC_API_BASE_URL` lives in `frontend/.env.local`.

CORS allows any `localhost`/`127.0.0.1` port in the `30xx` range, because
Next falls back to 3001, 3002, ... when 3000 is already taken. If the UI
reports *"Could not reach the backend"*, check which port Next actually
started on — the message names the API base URL it tried.

**Query Understanding has two paths.** Groq via `langchain-groq` with a Pydantic
schema is primary. If the key is missing, the call fails, or the output does not
satisfy the schema, a deterministic regex parser takes over and the UI labels the
parse as rule-based. The demo cannot be blocked by network or quota.

---

## How the interesting parts work

### No evidence-to-system mapping

The POC does not know which database holds which evidence. It walks the sources
in `app/catalog/databases.yaml` order, asks each only for what is still missing,
and folds every strong identifier it discovers into the search context so later
sources can be queried with keys the original request never contained.

The four sources present as **Oracle ERP**, **SAP Ariba**, **Sharepoint** and
**DB-04**. Their ids (`DB-01`…`DB-04`) stay stable internally; renaming them in
the registry changes every label in the UI.

### Some evidence is compiled, not retrieved

Not every required item is a document sitting in a source system. UC-01's sixth
item, **GL Transaction Listing (Excel)**, is the underlying row-level data:
the GL lines scoped to the requested period, SOB, NAC range **and report
type**, gathered from all four sources through MCP and written as a single
`.xlsx` with a criteria header, frozen panes, an auto-filter and a total row.
An AP request yields ~44 AP lines out of the 131 in period/SOB/NAC scope.

The catalog marks it `generated: tabular`, which tells the Retrieval Agent to
**build** it rather than search for a file. From that point it is
indistinguishable from a retrieved document: it stages, validates, appears in
the evidence table and ships in the package ZIP.

Because it has no single source system it is recorded against a synthetic
`GENERATED` id, shown as **Compiled extract**, with the contributing databases,
row count and total value in its metadata. Its row fetches are deliberately
excluded from the per-database match counts — otherwise "2 matches" would
become "35 matches" and mean nothing.

> **report_type filters the extract but NOT the documents.** An AP cost drill
> request still *requires* the AP, AR and Others reports as documents, so the
> shared matcher deliberately ignores `report_type`. The transaction listing
> behind that same request should hold AP lines only, so the filter is applied
> as a separate exact-match layer on the `fetch_transactions` MCP tool. Leaking
> it into the matcher would stop an AP request ever finding the AR and Others
> documents, and the checklist could never complete — there is a test guarding
> exactly that.

> **One subtlety worth knowing.** Aggregates are compiled against the
> auditor's *stated* scope, never the enriched search context. Identifier
> enrichment is right for correlating documents (find the PO for this invoice)
> but wrong here: a `vendor_id` harvested mid-run once narrowed the listing
> from 131 rows to 57 without any error. `scope_context` is threaded through
> the agent specifically to prevent that, and a test asserts the sheet contains
> every in-scope row and only SOB 101 / NAC 5000-5999.

To add tabular evidence to another use case, declare it in `use_cases.yaml`
with `generated: tabular`. No code change.

### Mandatory inputs are enforced before any search

A request can be understood and still be unsearchable. `"Provide cost drill
report for August 2026."` classifies correctly as UC-01, but a cost drill needs
**SOB, NAC range and report type** to select the right documents. Searching on
period alone does not fail loudly — against a real ERP it returns whichever
document came back first, presented as validated evidence. Wrong, confidently.

So `check_required_inputs` compares the parsed parameters against the use
case's `required_parameters` and, if any are absent, **halts before touching a
source system**: status `NEEDS_INPUT`, zero databases searched, and a question
put to the auditor.

The answer is free text. It is appended to the request and the whole thing is
re-parsed, so `"SOB 101, NAC 5000-5999, AP"` fills the gaps. A partial answer
narrows the question instead of restarting it, and retrieval resumes
automatically once every mandatory input is known. `raw_query` is never
rewritten — clarifications are recorded separately so the trail stays honest.

This applies to all four use cases, driven entirely by the catalog:

| Use case | Mandatory inputs |
|---|---|
| UC-01 | period, sob, nac_range, report_type |
| UC-02 | account, period |
| UC-03 | period *(vendor/sample optional)* |
| UC-04 | vendor_name, invoice_number |

### The retry is structural, not scripted

For the demo query, `DB-03` holds the SES document keyed **only** on
`ses_number` — every other identifier column is NULL. `ses_number` is not
knowable until `DB-04` (searched *after* DB-03) reveals it on the supporting
document. So:

| Pass | What happens |
|---|---|
| 1 | Oracle ERP → Invoice, GRN · SAP Ariba → PO · Sharepoint → **nothing** · DB-04 → Supporting Doc, which reveals `ses_number = SES-455` |
| — | Validation returns `INCOMPLETE` (SES missing) |
| 2 | Re-search with the enriched context → Sharepoint hits |

`retry_count = 1` falls out of real mechanics, with no special-casing anywhere.

> The mockup's caption says SES was recovered "via related identifiers from
> DB-01". That is not reachable: whichever source reveals the key must be
> searched *after* DB-03, or the first pass would already find it. The app
> generates this sentence from recorded state, so it says DB-04 — the source
> that actually supplied the key.

### MCP layer

`app/mcp_layer/server.py` is the only module that opens a source database. It
exposes `search_sqlite_database`, `get_document_metadata` and
`retrieve_document` over a real MCP client/server pair using the SDK's
in-memory transport, so tool calls are genuine JSON-RPC round trips with no
subprocess to supervise. `retrieval_agent.py` never imports `sqlite3`.

### One payload per screen

`GET /api/audit-requests/{id}` returns everything the detail screen renders,
including a backend-computed `timeline[]`. The number of database steps derives
from the registry, so changing `databases.yaml` changes the UI with no frontend
edit. The frontend holds no workflow logic.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/audit-requests` | `{query}` → `{request_id, status}` |
| `GET /api/audit-requests` | List, for the Requests screen |
| `GET /api/audit-requests/{id}` | Composite state the UI polls |
| `POST /api/audit-requests/{id}/run` | Start the workflow (background) |
| `POST /api/audit-requests/{id}/retry` | Retry missing evidence |
| `POST /api/audit-requests/{id}/clarify` | `{answer}` — supply missing mandatory inputs and resume |
| `POST /api/audit-requests/{id}/review` | `{action: APPROVE\|REJECT\|RETRY, comment}` |
| `GET /api/audit-requests/{id}/package` | Summary, contents, review trail |
| `GET /api/audit-requests/{id}/package/download` | The whole package as a ZIP — what **Open Package** serves |
| `GET /api/audit-requests/{id}/package/files` | JSON manifest: absolute path and file list |
| `GET /api/audit-requests/{id}/evidence/{evid}/file` | Serves a staged document |
| `GET /api/use-cases` | The four catalog entries |
| `GET /health` | Config and database availability |

Interactive docs at <http://127.0.0.1:8000/docs>.

---

## Screens

| Route | Screen |
|---|---|
| `/audit` | Audit Request |
| `/requests` | Requests list |
| `/requests/{id}` | Detail & progress |
| `/requests/{id}/review` | Reviewer |
| `/requests/{id}/package` | Final package |
| `/use-cases` | Use case catalog |

---

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

30 tests covering TC-01…TC-10, the mandatory-input gate, the
clarify-and-resume turn and the compiled Excel extract, plus invariants (source documents never mutated,
retry bounded, package reproducible, evidence files confined to their request).
Each run uses a throwaway data root with freshly seeded databases.

Against a running server, all four use cases and the error paths:

```powershell
.\.venv\Scripts\python.exe scripts\verify_all_use_cases.py
```

Diagnostics: `probe_search.py` (replays the two-pass search),
`probe_workflow.py` (full workflow, no API), `probe_api.py` (every endpoint).

Screens, for visual comparison against `UI_SCREENS/`:

```powershell
cd frontend
node scripts\screenshot.mjs <REQUEST_ID> ..\screenshots
```

---

## Layout

```
backend/
  app/
    catalog/       use_cases.yaml + databases.yaml (the Requirement Catalog)
    mcp_layer/     MCP server, client, matching rules
    agents/        query understanding (+ rule fallback), retrieval agent
    graph/         LangGraph state, nodes, workflow
    services/      state db, repository, staging, validation, packaging, runner
    api/           routes + composite view builders
  scripts/         seeding, init, probes, verification
  tests/           TC-01 … TC-10
  databases/       db01…db04.sqlite          (generated)
  mock_documents/  synthetic PDFs            (generated)
  evidence_staging/{request_id}/             (generated)
  final_audit_packages/{request_id}/         (generated)
frontend/src/
  app/             routes
  components/      cards, tables, timeline, badges
  lib/             api client, types, polling hook, formatting
```

Generated directories are safe to delete; re-run the two seed scripts.

---

## Notes

- **Source documents are never modified.** Staging and packaging copy only, and
  a test asserts source mtimes are unchanged.
- **Secrets are never logged.** Startup reports only whether a key is present.
- `npm audit` reports two advisories against the `postcss` copy bundled inside
  `next`. They concern processing untrusted CSS, which this app never does, and
  clearing them requires a breaking upgrade to Next 16. The direct `postcss`
  dependency is patched.
- Out of scope per the specs: authentication, deployment, real enterprise
  connections, evidence-to-system mapping, and any LLM-authored audit judgement.
  UC-02's long-outstanding explanation is surfaced as human-required and is
  never generated.

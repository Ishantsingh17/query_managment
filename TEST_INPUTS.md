# Test Inputs

Every query below was executed against the running app and the outcomes are
**measured, not predicted**. Re-run them all at any time:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\test_inputs.py
```

That writes `backend\test_input_results.json` with the full detail for each.

Type these into the **Audit Requirement** box on `/audit` and press
**Start Retrieval**. With the default `DEMO_STEP_DELAY_MS=700` each run takes
roughly 10–20 seconds, and the timeline advances `DB-01 → DB-04` as you watch.

---

## Start here — the primary demo

```
Provide alternate testing documents for ABC Ltd, Invoice INV-12345.
```

| | |
|---|---|
| Use case | **UC-04** — Balance Confirmation Alternate Testing |
| Parameters | Vendor `ABC Ltd`, Invoice Number `INV-12345` |
| Evidence | **5 of 5** |
| Sources | Oracle ERP (×2), SAP Ariba, Sharepoint, DB-04 — all four |
| Retries | **1** |
| Validation | **COMPLETE** (5 checks pass) |
| Final status | READY FOR REVIEW |

This is the one to show. Watch for:

- The timeline reads `Oracle ERP · 2 matches · Invoice, GRN` → `SAP Ariba · 1 match · Purchase Order` → `Sharepoint · 1 match · SES` → `DB-04 · 1 match · Supporting Document`
- **Retry note:** *"1 retry performed — SES was found in Sharepoint on a later attempt via related identifiers from DB-04."*
- SES was genuinely missed on the first pass. Sharepoint holds it keyed only on `ses_number`, and that key is not knowable until DB-04 — searched *after* Sharepoint — reveals it. Nothing is scripted.
- Then **Review Package → Approve Package** to reach the final package screen.

---

## All test inputs

| ID | Query | Use case | Evidence | Validation | Retries |
|---|---|---|---|---|---|
| **A1** | `Provide AP Cost Drill for August 2026, SOB 101, NAC 5000–5999.` | UC-01 | 6/6 | COMPLETE | 0 |
| **A2** | `Provide AP Cost Drill for August 2026, SOB 101, NAC 5000-5999.` | UC-01 | 6/6 | COMPLETE | 0 |
| **A3** | `Provide AR Cost Drill for August 2026, SOB 101, NAC 5000-5999.` | UC-01 | 6/6 | COMPLETE | 0 |
| **A4** | `Provide AP Cost Drill for September 2026, SOB 101, NAC 5000-5999.` | UC-01 | 5/6 | NEEDS_REVIEW | 2 |
| **A5** | `Expense drill for Aug 2026, SOB 101, NAC range 5000 to 5999, report type AP` | UC-01 | 6/6 | COMPLETE | 0 |
| **A6** | `Provide cost drill report for August 2026.` | UC-01 | — | **NEEDS_INPUT** | 0 |
| **B1** | `Prepare schedules for account 4100 for June 2026.` | UC-02 | 5/6 | NEEDS_REVIEW | 0 |
| **B2** | `I need the ledger extract and ageing for account 4100, June 2026.` | UC-02 | 5/6 | NEEDS_REVIEW | 0 |
| **B3** | `Prepare account schedule for account 4100 period June 2026 with movement details.` | UC-02 | 5/6 | NEEDS_REVIEW | 0 |
| **C1** | `Prepare trade payables ageing schedule as at 30 June 2026.` | UC-03 | 5/5 | COMPLETE | 0 |
| **C2** | `Provide trade payables balance confirmation samples as at 30 June 2026.` | UC-03 | 5/5 | COMPLETE | 0 |
| **C3** | `Balance confirmation samples for vendor ABC Ltd as at 30 June 2026.` | UC-03 | 5/5 | COMPLETE | 0 |
| **D1** | `Provide alternate testing documents for ABC Ltd, Invoice INV-12345.` | UC-04 | 5/5 | COMPLETE | 1 |
| **D2** | `Alternate testing documents for Delta Services, Invoice INV-22222.` | UC-04 | 4/5 | NEEDS_REVIEW | 2 |
| **D3** | `Provide alternate testing documents for XYZ Traders, Invoice INV-99999.` | UC-04 | 2/5 | NEEDS_REVIEW | 2 |
| **D4** | `Give me the invoice, PO and GRN for Delta Services invoice INV-22222.` | UC-04 | 4/5 | NEEDS_REVIEW | 2 |
| **E1** | `What is the weather in Muscat today?` | — | — | — | UNSUPPORTED |
| **F1** | `Prepare schedules for June 2026.` | UC-02 | — | **NEEDS_INPUT** (asks Account) | 0 |
| **F2** | `Provide trade payables balance confirmation samples.` | UC-03 | — | **NEEDS_INPUT** (asks Period) | 0 |
| **F3** | `Provide alternate testing documents for ABC Ltd.` | UC-04 | — | **NEEDS_INPUT** (asks Invoice Number) | 0 |
| **E2** | `Please prepare the statutory audit report and give your opinion.` | — | — | — | UNSUPPORTED |

---

## What each group demonstrates

### A — UC-01 Cost Drill / Expense Drill

**UC-01 has six required items, not five.** The sixth is
**GL Transaction Listing (Excel)** — the row-level data behind the reports,
compiled rather than retrieved. On any completed A-series request:

- the evidence table shows it with a green spreadsheet icon, the **row count**
  in place of an identifier, and **Compiled extract** as the source
- it is filtered to the **report type you asked for**: A1/A2 (AP) give ~44 AP
  lines, A3 (AR) gives ~44 AR lines — out of the 131 rows in period/SOB/NAC
  scope. Open the sheet and check the Report Type column holds one value
- **View** downloads a real `.xlsx`: criteria header, frozen panes,
  auto-filter, and a total row
- open it and check the scope — every line is SOB 101 with a NAC code inside
  5000–5999. The seed deliberately includes 12 rows for another SOB and 8
  outside the range; none of them appear
- the workbook also ships inside the package ZIP

Note what does **not** get filtered: the checklist still requires and
retrieves the AP, AR **and** Others cost drill *documents*, because a cost
drill engagement needs all three. Only the data extract narrows to the
requested type.

The per-source match counts stay at 2 / 1 / 2 — the row fetches are not
counted as document matches.

**A1 / A2 — en dash vs hyphen.** Both parse `NAC 5000-5999` identically. A1 uses
the en dash exactly as the Screen 1 example does; the parser normalises dash
characters, so copy-paste from a spec document works.

**A3 — report type does not narrow the checklist.** Asking for the *AR* drill
still requires and retrieves all three cost drill reports (AP, AR, Others).
Report type is validated as *"Requested report type retrieved"* rather than
filtered on, which is why AR and Others are not treated as mismatches.

**A4 — missing evidence, retries exhausted.** September 2026 has no Others
report in any source. Expect `4/5`, missing **Cost Drill Report — Others**,
`NEEDS_REVIEW`, and exactly **2** retries (the `MAX_RETRIES` bound) with the note
*"2 retries performed — no additional evidence was recovered."*

**A5 — loose wording.** `Aug 2026`, `NAC range 5000 to 5999` and `report type AP`
all parse. Period is kept verbatim as `Aug 2026` and still matches the
`August 2026` records, because period comparison expands month abbreviations.

**A6 — mandatory inputs omitted: the request HALTS.** This is the important
one. It classifies correctly as UC-01, then stops with **INPUT REQUIRED**
before searching anything:

- `databases_searched` is **0**, evidence is **0 of 5**, validation is absent
- the timeline shows *Requirements Identified* in **red / "Input required"**, with all four sources still PENDING
- a question appears: *"To search for Cost Drill / Expense Drill evidence I also need SOB, NAC Range and Report Type. Which values should I use?"*

Then answer it in the box. Try a **partial** answer first — type `SOB 101` and
send: the question narrows to *NAC Range and Report Type* and it still refuses
to search. Now send `NAC 5000-5999 and report type AP`: the panel disappears,
retrieval resumes automatically, the timeline animates through Oracle ERP →
SAP Ariba → Sharepoint → DB-04, and it finishes **5 of 5, COMPLETE**.

Why it halts rather than proceeding: period alone would match every SOB and
NAC range for August 2026 in a real ERP, and the agent takes the first match
per evidence type — so it would return confidently wrong evidence. Refusing to
search is the safe answer; asking is the useful one.

The original query is never rewritten. Check the *Package Summary* after
approval: `raw_query` still reads exactly what you typed, with the
clarifications recorded separately.

### B — UC-02 Schedules

All three phrasings land on UC-02 with account `4100` and period `June 2026`,
and all three stop at **5 of 6**.

The sixth item, **Long Outstanding Balance Explanations**, is marked
`human_required` in the requirement catalog. It needs auditor judgement, so it
is never generated and never retried — hence `0` retries and
`NEEDS_REVIEW` with the headline **"Human Input Required"**. On the detail
screen that row carries a **HUMAN INPUT** badge instead of a status badge.

This is the one case where `NEEDS_REVIEW` is the correct final state rather
than a failure.

### C — UC-03 Trade Payables Balance Confirmation

**C1 / C2 — no vendor named.** Period alone (`30 June 2026`) retrieves all five
items across all four sources, with **no ambiguity reported**. Period is the
only mandatory input for UC-03; a vendor or sample list narrows the result when
supplied but its absence is not a gap, so the card lists it as an input while
the parse stays clean.

C1 is the deliberately ambiguous one — *"trade payables ageing **schedule**"*
reads as UC-02 on the word "schedule" alone. Both the prompt and the rule
parser resolve it to UC-03 because it concerns trade payables.

**C3 — vendor named.** The vendor appears in both `vendor_sample` and
`vendor_name`.

### D — UC-04 Balance Confirmation Alternate Testing

**D1 — the primary demo.** See the top of this document.

**D2 — evidence that does not exist.** Delta Services has an invoice, PO, GRN
and supporting document but no SES anywhere. Expect `4/5`, missing **SES**,
`NEEDS_REVIEW` after **2** retries. This proves the retry loop terminates
rather than spinning.

**D3 — identifier discrimination.** XYZ Traders / INV-99999 has only an invoice
(Oracle ERP) and a PO (SAP Ariba). Expect `2/5` with **GRN, SES, Supporting
Document** missing. Crucially, it does **not** pick up ABC Ltd's paperwork: a
disagreement on any shared identifier disqualifies a row, so INV-12345's
documents are never returned here.

**D4 — classified by content, not by phrase.** No "alternate testing" wording at
all, yet the vendor plus invoice number still route it to UC-04.

### E — Rejections

Both return `UNSUPPORTED` with no retrieval attempted (`0` databases searched),
and the detail screen shows the spec's message:

> This POC supports four audit requirements: Cost Drill, Schedules, Trade
> Payables Balance Confirmation Samples, and Balance Confirmation Alternate
> Testing.

**E2** matters more than E1: it is audit-flavoured and asks for an opinion,
which is explicitly out of scope. It must still be refused.

---

## Reviewer actions

Run **D1** first, then from `/requests/{id}/review`:

| Action | Expected |
|---|---|
| **Approve Package** | Status → `APPROVED`, redirects to the package screen, green *"Evidence package approved"* banner, trail gains **Package approved · J. Al-Farsi** |
| **Request Retry** | Status → `RETRIEVING`, returns to detail, re-searches only what is missing, then settles again |
| **Reject** | Status → `REJECTED` |

Comments are optional and appear on the request afterwards.

---

## Non-query tests

### Evidence file serving

On any completed request, click **View** on each row of *Retrieved Evidence*.
Each opens a real generated PDF in a new tab. On the package screen the same
works for all five files.

### Open Package

On the final package screen, **Open Package** downloads
`{REQUEST_ID}_audit_evidence_package.zip` containing `evidence/` plus
`summary.json`, `retrieval_summary.json` and `validation_summary.json`.

The JSON manifest (absolute path and file list) is still available for scripting
at `GET /api/audit-requests/{id}/package/files`.

### Empty state

Visit `/requests` before submitting anything (or after deleting
`backend\app_state.sqlite` and re-running `init_app_state.py`):

> No audit requests yet. Start by entering an audit requirement.

### Missing input

Press **Start Retrieval** with the box empty:

> Required inputs are missing. Please provide the highlighted values.

### TC-10 — database unavailable

Simulate a source outage. With the backend **stopped**:

```powershell
cd backend
Rename-Item databases\db03.sqlite db03.sqlite.bak
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Now run **D1**. Expected:

- The run still completes rather than crashing
- Evidence is retrieved from Oracle ERP, SAP Ariba and DB-04
- The **Sharepoint** timeline node turns **red / Unavailable**
- **SES** is reported missing (it lived only in Sharepoint)
- The retrieval log records `DATABASE_UNAVAILABLE` for DB-03

Restore afterwards:

```powershell
Rename-Item databases\db03.sqlite.bak db03.sqlite
```

---

## Source systems

The four mock sources present as the systems they stand in for. Ids stay stable
internally; the names are what the UI shows.

| Id | Name | Holds (for the demo query) |
|---|---|---|
| DB-01 | **Oracle ERP** | Invoice, GRN |
| DB-02 | **SAP Ariba** | Purchase Order |
| DB-03 | **Sharepoint** | SES — reachable only after DB-04 reveals its number |
| DB-04 | **DB-04** | Supporting Document |

Rename them in `backendpp\catalog\databases.yaml`; the timeline, evidence
table and search summary all follow, and so does the search order.

---

## Notes on what you are seeing

**Groq is live.** `GROQ_MODEL` is set to `openai/gpt-oss-120b`, which your key
can reach. All 18 queries above ran through the LLM path (`parse_source: GROQ`)
with confidence 0.95–1.00, and the understanding card shows the model name
rather than the rule-based notice.

Classifications and evidence counts are **identical** on both paths — the LLM
changes confidence and wording robustness, while the requirement catalog,
retrieval and validation stay deterministic. To see the fallback instead, blank
out `GROQ_API_KEY` in `backend\.env` and re-run: same use cases, same evidence,
confidence 0.69–0.95.

Models available to your key (via `client.models.list()`):

| Model | Suitable here? |
|---|---|
| `openai/gpt-oss-120b` | **Yes — in use.** 10/10 classification, no fallbacks |
| `openai/gpt-oss-20b` | Works, but fell back to rules on 1 of 10 (flaky tool call) |
| `qwen/qwen3.8-27b`, `qwen/qwen3.6-27b` | No — tool calling fails |
| `groq/compound`, `groq/compound-mini` | No — tool calling unsupported |
| `allam-2-7b` | Arabic-focused, not evaluated |
| `whisper-large-v3`, `whisper-large-v3-turbo` | Speech-to-text |
| `canopylabs/orpheus-*` | Text-to-speech |
| `meta-llama/llama-prompt-guard-2-*` | Safety classifiers, not chat |
| `openai/gpt-oss-safeguard-20b` | Safety model, not chat |

To re-check what your key can reach:

```powershell
cd backend
.\.venv\Scripts\python.exe -c "from groq import Groq; from app.config import get_settings; [print(m.id) for m in Groq(api_key=get_settings().groq_api_key).models.list().data]"
```

Compare candidates on the classification task:

```powershell
$env:GROQ_MODEL="openai/gpt-oss-20b"
.\.venv\Scripts\python.exe scripts\compare_models.py
```

**`READY_FOR_REVIEW` with `NEEDS_REVIEW` validation is not a contradiction.**
The request status says *the package is ready for a human to look at*; the
validation status says *why it needs looking at*. A4, B1–B3, D2–D4 all land
there deliberately.

**Request IDs increment and never repeat.** The counter starts so the first
request is `AUD-00124`, matching the mockups. Re-running the batch produces new
ids each time; the ids in `test_input_results.json` are from the last run.

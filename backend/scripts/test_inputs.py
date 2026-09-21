"""Run the full catalogue of test-input queries and report actual outcomes.

Every query documented in TEST_INPUTS.md is executed here, so the documented
expectations are measured rather than assumed.

Usage: python scripts/test_inputs.py [base_url]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

# (id, use case group, query, note)
QUERIES: list[tuple[str, str, str, str]] = [
    # --- UC-01 Cost Drill -------------------------------------------------
    ("A1", "UC-01", "Provide AP Cost Drill for August 2026, SOB 101, NAC 5000–5999.",
     "Screen 1 example, en dash"),
    ("A2", "UC-01", "Provide AP Cost Drill for August 2026, SOB 101, NAC 5000-5999.",
     "Same, plain hyphen"),
    ("A3", "UC-01", "Provide AR Cost Drill for August 2026, SOB 101, NAC 5000-5999.",
     "AR requested; all three drills still required"),
    ("A4", "UC-01", "Provide AP Cost Drill for September 2026, SOB 101, NAC 5000-5999.",
     "Others report absent for September"),
    ("A5", "UC-01", "Expense drill for Aug 2026, SOB 101, NAC range 5000 to 5999, report type AP",
     "Abbreviated month, 'to' range, alternate wording"),
    ("A6", "UC-01", "Provide cost drill report for August 2026.",
     "Mandatory SOB / NAC / report type omitted"),

    # --- UC-02 Schedules --------------------------------------------------
    ("B1", "UC-02", "Prepare schedules for account 4100 for June 2026.",
     "Straightforward schedule request"),
    ("B2", "UC-02", "I need the ledger extract and ageing for account 4100, June 2026.",
     "Alternate wording"),
    ("B3", "UC-02", "Prepare account schedule for account 4100 period June 2026 with movement details.",
     "Verbose wording"),

    # --- UC-03 Trade Payables --------------------------------------------
    ("C1", "UC-03", "Prepare trade payables ageing schedule as at 30 June 2026.",
     "Screen 1 example; no vendor named"),
    ("C2", "UC-03", "Provide trade payables balance confirmation samples as at 30 June 2026.",
     "Explicit confirmation-sample wording"),
    ("C3", "UC-03", "Balance confirmation samples for vendor ABC Ltd as at 30 June 2026.",
     "Vendor named"),

    # --- UC-04 Alternate Testing -----------------------------------------
    ("D1", "UC-04", "Provide alternate testing documents for ABC Ltd, Invoice INV-12345.",
     "PRIMARY DEMO - multi-DB plus a real retry"),
    ("D2", "UC-04", "Alternate testing documents for Delta Services, Invoice INV-22222.",
     "SES exists nowhere; retries exhaust"),
    ("D3", "UC-04", "Provide alternate testing documents for XYZ Traders, Invoice INV-99999.",
     "Only part of the chain exists"),
    ("D4", "UC-04", "Give me the invoice, PO and GRN for Delta Services invoice INV-22222.",
     "Classified by identifiers, not by the phrase"),

    # --- Rejections -------------------------------------------------------
    ("E1", "UNSUPPORTED", "What is the weather in Muscat today?",
     "Plainly out of scope"),
    ("E2", "UNSUPPORTED", "Please prepare the statutory audit report and give your opinion.",
     "Audit-flavoured but outside the four requirements"),
]


def post(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else b"{}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        # Decode explicitly; json.load on the raw stream can mangle non-ASCII.
        return json.loads(response.read().decode("utf-8"))


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}") as response:
        return json.loads(response.read().decode("utf-8"))


def run(query: str, timeout: float = 120.0) -> dict:
    created = post("/api/audit-requests", {"query": query})
    request_id = created["request_id"]
    post(f"/api/audit-requests/{request_id}/run")

    deadline = time.time() + timeout
    detail = get(f"/api/audit-requests/{request_id}")
    while detail.get("is_active") and time.time() < deadline:
        time.sleep(0.6)
        detail = get(f"/api/audit-requests/{request_id}")
    return detail


def main() -> int:
    print(f"Running {len(QUERIES)} test inputs against {BASE}\n")
    rows = []

    for test_id, group, query, note in QUERIES:
        detail = run(query)
        validation = (detail.get("validation") or {}).get("validation_status") or "-"
        params = {p["key"]: p["value"] for p in detail.get("parameters", [])}

        rows.append(
            {
                "id": test_id,
                "group": group,
                "query": query,
                "note": note,
                "request_id": detail["request_id"],
                "status": detail["status"],
                "use_case": detail.get("use_case_id") or "-",
                "confidence": detail.get("confidence"),
                "found": detail["evidence_found_count"],
                "required": detail["evidence_required_count"],
                "validation": validation,
                "retries": detail["retry_count"],
                "sources": sorted(
                    {r["source_database_id"] for r in detail.get("retrieved_evidence", [])}
                ),
                "missing": detail.get("missing_evidence", []),
                "ambiguities": detail.get("ambiguities", []),
                "parameters": params,
                "retry_note": detail.get("retry_note"),
            }
        )

        print(f"[{test_id}] {detail['request_id']}  {query}")
        print(
            f"      -> {detail['status']} | {detail.get('use_case_id') or '-'}"
            f" | conf {detail.get('confidence')}"
            f" | evidence {detail['evidence_found_count']}/{detail['evidence_required_count']}"
            f" | validation {validation} | retries {detail['retry_count']}"
        )
        if params:
            print(f"         params    : {params}")
        if rows[-1]["sources"]:
            print(f"         sources   : {', '.join(rows[-1]['sources'])}")
        if rows[-1]["missing"]:
            print(f"         missing   : {rows[-1]['missing']}")
        if rows[-1]["ambiguities"]:
            print(f"         ambiguity : {rows[-1]['ambiguities']}")
        if rows[-1]["retry_note"]:
            print(f"         retry     : {rows[-1]['retry_note']}")
        print()

    out = "test_input_results.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    # Sanity: every query must reach a settled state, never hang or error out.
    stuck = [r["id"] for r in rows if r["status"] in ("RECEIVED", "RETRIEVING", "VALIDATING")]
    errored = [r["id"] for r in rows if r["status"] == "ERROR"]
    if stuck:
        print(f"\nFAIL: still active: {stuck}")
    if errored:
        print(f"\nFAIL: errored: {errored}")
    return 1 if (stuck or errored) else 0


if __name__ == "__main__":
    raise SystemExit(main())

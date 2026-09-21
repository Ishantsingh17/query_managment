"""Run every representative scenario against a live backend.

Usage: python scripts/verify_all_use_cases.py [base_url]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

SCENARIOS = [
    {
        "name": "TC-01  UC-01 complete (5 documents + compiled extract)",
        "query": "Provide AP Cost Drill for August 2026, SOB 101, NAC 5000-5999.",
        "expect": {"use_case_id": "UC-01", "validation": "COMPLETE", "found": 6},
    },
    {
        "name": "TC-02  UC-01 missing report",
        "query": "Provide AP Cost Drill for September 2026, SOB 101, NAC 5000-5999.",
        "expect": {"use_case_id": "UC-01", "validation": "NEEDS_REVIEW", "found": 5},
    },
    {
        "name": "TC-03  UC-02 schedules",
        "query": "Prepare schedules for account 4100 for June 2026.",
        "expect": {"use_case_id": "UC-02", "validation": "NEEDS_REVIEW", "found": 5},
    },
    {
        "name": "TC-05  UC-03 confirmations",
        "query": "Prepare trade payables ageing schedule as at 30 June 2026.",
        "expect": {"use_case_id": "UC-03", "validation": "COMPLETE", "found": 5},
    },
    {
        "name": "TC-06/07  UC-04 multi-DB + retry",
        "query": "Provide alternate testing documents for ABC Ltd, Invoice INV-12345.",
        "expect": {"use_case_id": "UC-04", "validation": "COMPLETE", "found": 5, "retries": 1},
    },
    {
        "name": "TC-08  unsupported",
        "query": "What is the weather in Muscat today?",
        "expect": {"status": "UNSUPPORTED"},
    },
    {
        "name": "TC-09  missing mandatory input halts before searching",
        "query": "Provide cost drill report for August 2026.",
        "expect": {
            "use_case_id": "UC-01",
            "status": "NEEDS_INPUT",
            "found": 0,
            "databases_searched": 0,
        },
    },
]


def post(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else b"{}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}") as response:
        return json.load(response)


def run(query: str, timeout: float = 90.0) -> dict:
    created = post("/api/audit-requests", {"query": query})
    request_id = created["request_id"]
    post(f"/api/audit-requests/{request_id}/run")

    deadline = time.time() + timeout
    detail = get(f"/api/audit-requests/{request_id}")
    while detail.get("is_active") and time.time() < deadline:
        time.sleep(1.0)
        detail = get(f"/api/audit-requests/{request_id}")
    return detail


def main() -> int:
    failures: list[str] = []
    print(f"Verifying against {BASE}\n")

    for scenario in SCENARIOS:
        detail = run(scenario["query"])
        expect = scenario["expect"]
        validation = (detail.get("validation") or {}).get("validation_status")

        print(f"{scenario['name']}")
        print(f"  query      : {scenario['query']}")
        print(
            f"  result     : {detail['status']} | {detail.get('use_case_id')}"
            f" | evidence {detail['evidence_found_count']}/{detail['evidence_required_count']}"
            f" | validation {validation} | retries {detail['retry_count']}"
        )
        if detail.get("retry_note"):
            print(f"  retry note : {detail['retry_note']}")
        if detail.get("ambiguities"):
            print(f"  ambiguities: {detail['ambiguities']}")

        problems = []
        if "use_case_id" in expect and detail.get("use_case_id") != expect["use_case_id"]:
            problems.append(f"use case {detail.get('use_case_id')} != {expect['use_case_id']}")
        if "status" in expect and detail["status"] != expect["status"]:
            problems.append(f"status {detail['status']} != {expect['status']}")
        if "validation" in expect and validation != expect["validation"]:
            problems.append(f"validation {validation} != {expect['validation']}")
        if "found" in expect and detail["evidence_found_count"] != expect["found"]:
            problems.append(f"found {detail['evidence_found_count']} != {expect['found']}")
        if "retries" in expect and detail["retry_count"] != expect["retries"]:
            problems.append(f"retries {detail['retry_count']} != {expect['retries']}")
        if expect.get("ambiguities") and not detail.get("ambiguities"):
            problems.append("expected ambiguities to be reported")
        if "databases_searched" in expect and detail["databases_searched"] != expect["databases_searched"]:
            problems.append(
                f"databases_searched {detail['databases_searched']} != {expect['databases_searched']}"
            )

        if problems:
            print(f"  FAIL       : {'; '.join(problems)}")
            failures.append(f"{scenario['name']}: {'; '.join(problems)}")
        else:
            print("  OK")
        print()

    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All scenarios behaved as expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

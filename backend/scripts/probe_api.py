"""Diagnostic: exercise every endpoint against the demo query.

Run: python scripts/probe_api.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DEMO_QUERY = "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."


def main() -> int:
    problems: list[str] = []

    with TestClient(app) as client:
        health = client.get("/health").json()
        print("health:", json.dumps(health, indent=2)[:400])

        use_cases = client.get("/api/use-cases").json()
        print(f"\nuse-cases: {len(use_cases)}")
        for uc in use_cases:
            print(f"  {uc['use_case_id']}  {uc['short_name']:<40} inputs={uc['required_parameter_labels']}")
        if len(use_cases) != 4:
            problems.append(f"expected 4 use cases, got {len(use_cases)}")

        created = client.post("/api/audit-requests", json={"query": DEMO_QUERY})
        print(f"\ncreate -> {created.status_code} {created.json()}")
        request_id = created.json()["request_id"]

        # TestClient runs background tasks synchronously after the response.
        run = client.post(f"/api/audit-requests/{request_id}/run")
        print(f"run -> {run.status_code}")

        detail = client.get(f"/api/audit-requests/{request_id}").json()
        print(f"\nstatus            : {detail['status']}")
        print(f"use case          : {detail['use_case_id']} - {detail['requirement_name']}")
        print(f"confidence        : {detail['confidence']} ({detail['parse_source']})")
        print(f"parameters        : {[(p['label'], p['value']) for p in detail['parameters']]}")
        print(f"evidence          : {detail['evidence_found_count']} of {detail['evidence_required_count']}")
        print(f"retry count       : {detail['retry_count']}")
        print(f"retry note        : {detail['retry_note']}")
        print(f"databases searched: {detail['databases_searched']}")

        print("\nrequired evidence checklist:")
        for item in detail["required_evidence"]:
            print(
                f"  {item['label']:<24} {str(item['identifier']):<12}"
                f" {str(item['source_database_id']):<7} {item['status']}"
            )

        print("\ntimeline:")
        for step in detail["timeline"]:
            extra = f" | {step['detail']}" if step.get("detail") else ""
            sub = f" | {step['sub_detail']}" if step.get("sub_detail") else ""
            print(f"  {step['status']:<9} {step['label']:<24}{extra}{sub}")

        print("\nvalidation:")
        val = detail["validation"]
        print(f"  status: {val['validation_status']} - {val['headline']}: {val['message']}")
        for check in val["checks"]:
            print(f"    [{check['result']:<6}] {check['label']}")

        if detail["status"] != "READY_FOR_REVIEW":
            problems.append(f"expected READY_FOR_REVIEW, got {detail['status']}")
        if detail["evidence_found_count"] != 5:
            problems.append(f"expected 5 found, got {detail['evidence_found_count']}")
        if detail["retry_count"] != 1:
            problems.append(f"expected retry_count 1, got {detail['retry_count']}")

        # Evidence file serving (the View action).
        first = detail["retrieved_evidence"][0]
        file_response = client.get(
            f"/api/audit-requests/{request_id}/evidence/{first['evidence_id']}/file"
        )
        print(
            f"\nView {first['document_type_label']}: {file_response.status_code}"
            f" {file_response.headers.get('content-type')} {len(file_response.content)} bytes"
        )
        if file_response.status_code != 200:
            problems.append("evidence file download failed")

        # Package before approval.
        package = client.get(f"/api/audit-requests/{request_id}/package").json()
        print(f"\npackage path: {package['package_path']}  approved={package['approved']}")
        print("contents:")
        for row in package["contents"]:
            print(f"  {row['filename']:<30} {row['document_type_label']:<22} {row['source_database_id']}  {row['status']}")

        # Approve.
        approved = client.post(
            f"/api/audit-requests/{request_id}/review",
            json={"action": "APPROVE", "comment": "Reviewed", "reviewer_name": "J. Al-Farsi"},
        ).json()
        print(f"\nafter approve -> status={approved['status']} action={approved['review_action']}")
        if approved["status"] != "APPROVED":
            problems.append(f"expected APPROVED, got {approved['status']}")

        final_package = client.get(f"/api/audit-requests/{request_id}/package").json()
        print(f"approved={final_package['approved']} by={final_package['approved_by']}")
        print("\ntrail:")
        for entry in final_package["trail"]:
            print(f"  {entry['timestamp']}  {entry['label']:<28} {entry.get('detail')}")

        listing = client.get("/api/audit-requests").json()
        print(f"\nrequests list: {len(listing)} entries; newest = {listing[0]['request_id']} ({listing[0]['status']})")

        missing_404 = client.get("/api/audit-requests/AUD-99999")
        print(f"unknown request -> {missing_404.status_code}")
        if missing_404.status_code != 404:
            problems.append("expected 404 for unknown request")

    print()
    if problems:
        print("FAILURES:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: full API surface behaves as expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

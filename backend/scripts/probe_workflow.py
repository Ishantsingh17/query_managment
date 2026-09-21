"""Diagnostic: run the whole workflow for the demo query, with no API layer.

Run: python scripts/probe_workflow.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.services import db, packaging, repository, runner  # noqa: E402

DEMO_QUERY = "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."


async def main() -> int:
    settings = get_settings()
    settings.ensure_directories()
    db.initialize()

    request = repository.create_request(DEMO_QUERY)
    request_id = request["id"]
    print(f"request: {request_id}  status={request['status']}")

    await runner.run_workflow(request_id)

    snapshot = repository.get_workflow_state(request_id) or {}
    state = snapshot.get("state", {})
    final = repository.get_request(request_id) or {}
    validation = repository.latest_validation(request_id) or {}
    evidence = repository.list_retrieved_evidence(request_id)
    attempts = repository.list_retrieval_attempts(request_id)

    print(f"\nfinal status      : {final.get('status')}")
    print(f"use case          : {final.get('use_case_id')} - {final.get('requirement_name')}")
    print(f"confidence        : {state.get('confidence')} ({state.get('parse_source')})")
    print(f"retry count       : {state.get('retry_count')}")
    print(f"validation        : {validation.get('validation_status')}")
    print(f"retry note        : {state.get('retry_note')}")

    print(f"\nevidence ({len(evidence)}):")
    for item in evidence:
        staged = Path(item["staged_file_path"]).name if item.get("staged_file_path") else "NOT STAGED"
        print(
            f"  {item['document_type']:<22} {str(item['identifier']):<12}"
            f" {item['source_database_id']}  pass={item['pass_number']}  {staged}"
        )

    print(f"\nretrieval attempts ({len(attempts)}):")
    for attempt in attempts:
        print(
            f"  pass {attempt['pass_number']}  {attempt['database_id']}"
            f"  wanted={attempt['requested_evidence']}"
            f"  matches={attempt['result_count']}  {attempt['status']}"
        )

    print("\nvalidation checks:")
    for check in validation.get("checks", []):
        print(f"  [{check['result']:<6}] {check['label']}  - {check.get('detail')}")

    package = repository.get_package(request_id)
    print(f"\npackage path      : {package['package_path'] if package else None}")
    base = packaging.package_dir(request_id)
    if base.exists():
        for path in sorted(base.rglob("*")):
            if path.is_file():
                print(f"  {path.relative_to(base).as_posix()}  ({path.stat().st_size} bytes)")

    # --- assertions against the mockups ---------------------------------
    problems = []
    if final.get("status") != repository.STATUS_READY_FOR_REVIEW:
        problems.append(f"expected READY_FOR_REVIEW, got {final.get('status')}")
    if final.get("use_case_id") != "UC-04":
        problems.append(f"expected UC-04, got {final.get('use_case_id')}")
    if len(evidence) != 5:
        problems.append(f"expected 5 evidence items, got {len(evidence)}")
    if state.get("retry_count") != 1:
        problems.append(f"expected retry_count 1, got {state.get('retry_count')}")
    if validation.get("validation_status") != "COMPLETE":
        problems.append(f"expected COMPLETE, got {validation.get('validation_status')}")

    sources = {item["document_type"]: item["source_database_id"] for item in evidence}
    expected_sources = {
        "INVOICE": "DB-01", "GRN": "DB-01", "PURCHASE_ORDER": "DB-02",
        "SES": "DB-03", "SUPPORTING_DOCUMENT": "DB-04",
    }
    if sources != expected_sources:
        problems.append(f"source map mismatch: {sources}")

    ses = next((item for item in evidence if item["document_type"] == "SES"), None)
    if not ses or ses["pass_number"] != 2:
        problems.append("SES should have been found on the retry pass (pass 2)")

    print()
    if problems:
        print("FAILURES:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: end-to-end run matches the mockup exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

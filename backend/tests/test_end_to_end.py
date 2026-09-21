"""TC-01 to TC-10 from the implementation plan, plus supporting invariants."""

from __future__ import annotations

from pathlib import Path

import pytest


# ============================== TC-01 ==============================
def test_tc01_uc01_complete_retrieval(run_request):
    """A fully-supported cost drill request completes with all evidence."""
    detail = run_request(
        "Provide AP Cost Drill for August 2026, SOB 101, NAC 5000-5999."
    )

    assert detail["use_case_id"] == "UC-01"
    assert detail["status"] == "READY_FOR_REVIEW"
    # Five documents plus the compiled GL transaction listing.
    assert detail["evidence_required_count"] == 6
    assert detail["evidence_found_count"] == 6
    assert detail["validation"]["validation_status"] == "COMPLETE"
    assert detail["missing_evidence"] == []

    parameters = {p["key"]: p["value"] for p in detail["parameters"]}
    assert parameters["period"] == "August 2026"
    assert parameters["sob"] == "101"
    assert parameters["nac_range"] == "5000-5999"
    assert parameters["report_type"] == "AP"

    # All three cost drill reports are required even though the request named
    # only AP, so report_type must not act as a search filter.
    found = {item["document_type"] for item in detail["retrieved_evidence"]}
    assert {"COST_DRILL_AP", "COST_DRILL_AR", "COST_DRILL_OTHERS"} <= found


# ============================== TC-02 ==============================
def test_tc02_uc01_missing_report(run_request):
    """September has no Others report, so the request cannot complete."""
    detail = run_request(
        "Provide AP Cost Drill for September 2026, SOB 101, NAC 5000-5999."
    )

    assert detail["use_case_id"] == "UC-01"
    # Four documents plus the compiled extract; the Others report is missing.
    assert detail["evidence_found_count"] == 5
    assert detail["evidence_required_count"] == 6
    assert detail["validation"]["validation_status"] == "NEEDS_REVIEW"
    assert "COST_DRILL_OTHERS" in detail["validation"]["missing_evidence"]

    # The retry budget must be spent before giving up, and no further.
    assert detail["retry_count"] == 2

    checklist = {item["code"]: item["status"] for item in detail["required_evidence"]}
    assert checklist["COST_DRILL_OTHERS"] == "MISSING"


# ============================== TC-03 ==============================
def test_tc03_uc02_schedule_preparation(run_request):
    """Ledger, balances and ageing are assembled for the account schedule."""
    detail = run_request("Prepare schedules for account 4100 for June 2026.")

    assert detail["use_case_id"] == "UC-02"
    assert detail["evidence_required_count"] == 6

    found = {item["document_type"] for item in detail["retrieved_evidence"]}
    assert {
        "LEDGER_EXTRACT",
        "OPENING_BALANCE",
        "MOVEMENT_DETAILS",
        "CLOSING_BALANCE",
        "AGEING_REPORT",
    } <= found

    parameters = {p["key"]: p["value"] for p in detail["parameters"]}
    assert parameters["account"] == "4100"
    assert parameters["period"] == "June 2026"


# ============================== TC-04 ==============================
def test_tc04_uc02_long_outstanding_explanation_flagged(run_request):
    """The judgement item is flagged for a human, never auto-generated."""
    detail = run_request("Prepare schedules for account 4100 for June 2026.")

    checklist = {item["code"]: item for item in detail["required_evidence"]}
    explanation = checklist["LONG_OUTSTANDING_EXPLANATION"]

    assert explanation["human_required"] is True
    assert explanation["identifier"] is None
    assert detail["validation"]["validation_status"] == "NEEDS_REVIEW"

    # It is not retried, because no amount of searching can satisfy it.
    assert detail["retry_count"] == 0

    headline = detail["validation"]["headline"]
    assert "Human Input Required" in headline


# ============================== TC-05 ==============================
def test_tc05_uc03_confirmation_package(run_request):
    """The trade payables confirmation package assembles from period alone."""
    detail = run_request("Prepare trade payables ageing schedule as at 30 June 2026.")

    assert detail["use_case_id"] == "UC-03"
    assert detail["evidence_found_count"] == 5
    assert detail["validation"]["validation_status"] == "COMPLETE"

    found = {item["document_type"] for item in detail["retrieved_evidence"]}
    assert {
        "APTB",
        "AGEING_REPORT",
        "BALANCE_CONFIRMATION_LETTER",
        "VENDOR_CONTACT_DETAILS",
        "OUTSTANDING_INVOICE_DETAILS",
    } == found


# ============================== TC-06 ==============================
def test_tc06_uc04_evidence_across_multiple_databases(run_request, evidence_sources):
    """Evidence for one request is genuinely spread over four databases."""
    detail = run_request(
        "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."
    )

    sources = evidence_sources(detail)
    assert sources == {
        "INVOICE": "DB-01",
        "GRN": "DB-01",
        "PURCHASE_ORDER": "DB-02",
        "SES": "DB-03",
        "SUPPORTING_DOCUMENT": "DB-04",
    }
    assert len(set(sources.values())) == 4
    assert detail["databases_searched"] == 4

    # The unrelated vendor's paperwork must never be pulled in.
    identifiers = {item["identifier"] for item in detail["retrieved_evidence"]}
    assert "INV-99999" not in identifiers
    assert "PO-7777" not in identifiers


# ============================== TC-07 ==============================
def test_tc07_uc04_missing_ses_then_retry_success(client):
    """SES is missed on the first pass and recovered by the retry.

    This is the headline behaviour: DB-03 holds the SES row keyed only on
    ses_number, which is not knowable until DB-04 (searched later) reveals it.
    """
    created = client.post(
        "/api/audit-requests",
        json={"query": "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."},
    )
    request_id = created.json()["request_id"]
    client.post(f"/api/audit-requests/{request_id}/run")
    detail = client.get(f"/api/audit-requests/{request_id}").json()

    assert detail["retry_count"] == 1
    assert detail["validation"]["validation_status"] == "COMPLETE"
    assert detail["evidence_found_count"] == 5

    ses = next(i for i in detail["retrieved_evidence"] if i["document_type"] == "SES")
    assert ses["identifier"] == "SES-455"
    assert ses["source_database_id"] == "DB-03"

    # The first pass asked DB-03 for SES and got nothing; the second found it.
    from app.services import repository

    attempts = repository.list_retrieval_attempts(request_id)
    first = [a for a in attempts if a["pass_number"] == 1 and a["database_id"] == "DB-03"]
    second = [a for a in attempts if a["pass_number"] == 2 and a["database_id"] == "DB-03"]
    assert first and first[0]["result_count"] == 0
    assert second and second[0]["result_count"] == 1

    evidence = repository.list_retrieved_evidence(request_id)
    ses_row = next(i for i in evidence if i["document_type"] == "SES")
    assert ses_row["pass_number"] == 2

    # The note explains itself from recorded state rather than a fixed string.
    assert detail["retry_note"]
    assert "SES" in detail["retry_note"]
    assert "DB-04" in detail["retry_note"]


# ============================== TC-08 ==============================
def test_tc08_unsupported_query(run_request):
    """An out-of-scope request is rejected cleanly, with no retrieval."""
    detail = run_request("What is the weather in Muscat today?")

    assert detail["status"] == "UNSUPPORTED"
    assert detail["error_code"] == "UNSUPPORTED_QUERY"
    assert detail["retrieved_evidence"] == []
    assert detail["databases_searched"] == 0
    assert detail["validation"] is None

    timeline = {step["key"]: step["status"] for step in detail["timeline"]}
    assert timeline["query_understood"] == "ERROR"
    assert timeline["database_DB-01"] == "PENDING"


# ============================== TC-09 ==============================
def test_tc09_missing_mandatory_parameter_halts_before_searching(run_request):
    """A recognised but underspecified request must NOT search.

    A cost drill needs SOB, NAC range and report type to select the right
    documents. Searching on period alone would return whichever document came
    back first - confidently, and wrong - so the workflow stops and asks.
    """
    detail = run_request("Provide cost drill report for August 2026.")

    assert detail["use_case_id"] == "UC-01"
    assert detail["status"] == "NEEDS_INPUT"
    assert detail["error_code"] == "MISSING_REQUIRED_INPUT"

    # The decisive assertion: nothing was searched and nothing was retrieved.
    assert detail["databases_searched"] == 0
    assert detail["retrieved_evidence"] == []
    assert detail["evidence_found_count"] == 0
    assert detail["validation"] is None

    missing = [item["key"] for item in detail["missing_parameters"]]
    assert missing == ["sob", "nac_range", "report_type"]
    assert detail["clarification_question"]
    assert "SOB" in detail["clarification_question"]

    timeline = {step["key"]: step["status"] for step in detail["timeline"]}
    assert timeline["query_understood"] == "COMPLETE"
    assert timeline["requirements_identified"] == "ERROR"
    assert timeline["database_DB-01"] == "PENDING"


def test_gate_applies_to_every_use_case(client):
    """Every use case refuses to search without its mandatory inputs."""
    cases = [
        ("Provide cost drill report for August 2026.", "UC-01",
         ["sob", "nac_range", "report_type"]),
        ("Prepare schedules for June 2026.", "UC-02", ["account"]),
        ("Provide trade payables balance confirmation samples.", "UC-03", ["period"]),
        ("Provide alternate testing documents for ABC Ltd.", "UC-04",
         ["invoice_number"]),
    ]
    for query, use_case, expected_missing in cases:
        created = client.post("/api/audit-requests", json={"query": query})
        request_id = created.json()["request_id"]
        client.post(f"/api/audit-requests/{request_id}/run")
        detail = client.get(f"/api/audit-requests/{request_id}").json()

        assert detail["use_case_id"] == use_case, query
        assert detail["status"] == "NEEDS_INPUT", query
        assert detail["databases_searched"] == 0, query
        assert [i["key"] for i in detail["missing_parameters"]] == expected_missing, query


def test_clarification_resumes_the_run(client):
    """Answering the question completes the request."""
    created = client.post(
        "/api/audit-requests", json={"query": "Provide cost drill report for August 2026."}
    )
    request_id = created.json()["request_id"]
    client.post(f"/api/audit-requests/{request_id}/run")
    assert client.get(f"/api/audit-requests/{request_id}").json()["status"] == "NEEDS_INPUT"

    client.post(
        f"/api/audit-requests/{request_id}/clarify",
        json={"answer": "SOB 101, NAC 5000-5999, report type AP"},
    )
    detail = client.get(f"/api/audit-requests/{request_id}").json()

    assert detail["status"] == "READY_FOR_REVIEW"
    assert detail["missing_parameters"] == []
    assert detail["evidence_found_count"] == 6
    assert detail["validation"]["validation_status"] == "COMPLETE"

    parameters = {p["key"]: p["value"] for p in detail["parameters"]}
    assert parameters["sob"] == "101"
    assert parameters["nac_range"] == "5000-5999"
    assert parameters["report_type"] == "AP"


def test_partial_clarification_asks_again(client):
    """A partial answer narrows the question instead of proceeding."""
    created = client.post(
        "/api/audit-requests", json={"query": "Provide cost drill report for August 2026."}
    )
    request_id = created.json()["request_id"]
    client.post(f"/api/audit-requests/{request_id}/run")

    detail = client.post(
        f"/api/audit-requests/{request_id}/clarify", json={"answer": "SOB 101"}
    ).json()

    assert detail["status"] == "NEEDS_INPUT"
    assert detail["databases_searched"] == 0
    assert [i["key"] for i in detail["missing_parameters"]] == ["nac_range", "report_type"]

    # And finishing the answer then completes it.
    client.post(
        f"/api/audit-requests/{request_id}/clarify",
        json={"answer": "NAC 5000-5999 and AP"},
    )
    final = client.get(f"/api/audit-requests/{request_id}").json()
    assert final["status"] == "READY_FOR_REVIEW"
    assert final["evidence_found_count"] == 6


def test_clarification_preserves_the_original_query(client):
    """The auditor's original wording is never rewritten."""
    query = "Provide cost drill report for August 2026."
    created = client.post("/api/audit-requests", json={"query": query})
    request_id = created.json()["request_id"]
    client.post(f"/api/audit-requests/{request_id}/run")
    client.post(
        f"/api/audit-requests/{request_id}/clarify",
        json={"answer": "SOB 101, NAC 5000-5999, AP"},
    )
    detail = client.get(f"/api/audit-requests/{request_id}").json()

    assert detail["raw_query"] == query
    answers = [c["answer"] for c in detail["clarifications"]]
    assert answers == ["SOB 101, NAC 5000-5999, AP"]


def test_clarify_rejects_an_empty_answer(client):
    created = client.post(
        "/api/audit-requests", json={"query": "Provide cost drill report for August 2026."}
    )
    request_id = created.json()["request_id"]
    client.post(f"/api/audit-requests/{request_id}/run")

    response = client.post(f"/api/audit-requests/{request_id}/clarify", json={"answer": "   "})
    assert response.status_code == 400


# ============================== TC-10 ==============================
def test_tc10_database_search_failure_is_survivable(client, monkeypatch):
    """An unavailable source is recorded and the run continues elsewhere."""
    from app.catalog.loader import load_databases
    from app.config import get_settings

    settings = get_settings()
    db03 = next(s for s in load_databases() if s.database_id == "DB-03")
    path = db03.resolved_path(settings.data_root)

    backup = path.with_suffix(".sqlite.bak")
    path.rename(backup)
    try:
        created = client.post(
            "/api/audit-requests",
            json={"query": "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."},
        )
        request_id = created.json()["request_id"]
        client.post(f"/api/audit-requests/{request_id}/run")
        detail = client.get(f"/api/audit-requests/{request_id}").json()
    finally:
        backup.rename(path)

    # The run reached an orderly conclusion rather than crashing.
    assert detail["status"] in ("READY_FOR_REVIEW", "INCOMPLETE")
    assert detail["package_available"] is True

    # Evidence from the healthy databases was still retrieved.
    sources = {i["source_database_id"] for i in detail["retrieved_evidence"]}
    assert {"DB-01", "DB-02", "DB-04"} <= sources
    assert "DB-03" not in sources

    # The failure is visible, not swallowed.
    from app.services import repository

    attempts = repository.list_retrieval_attempts(request_id)
    failed = [a for a in attempts if a["database_id"] == "DB-03"]
    assert failed
    assert all(a["status"] == "DATABASE_UNAVAILABLE" for a in failed)

    timeline = {step["key"]: step for step in detail["timeline"]}
    assert timeline["database_DB-03"]["status"] == "ERROR"

    # SES lived only in DB-03, so it is correctly reported missing.
    assert "SES" in detail["validation"]["missing_evidence"]


# ========================= supporting invariants =========================
def test_source_documents_are_never_modified(run_request):
    """Staging and packaging copy; they must not touch the originals."""
    from app.config import get_settings

    settings = get_settings()
    sources = sorted(settings.mock_documents_dir.rglob("*"))
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in sources if p.is_file()}

    run_request("Provide alternate testing documents for ABC Ltd, Invoice INV-12345.")

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in sources if p.is_file()}
    assert before == after


def test_package_is_traceable_and_reproducible(client):
    """The generated package carries everything needed to audit the run."""
    import json

    from app.config import get_settings
    from app.services import packaging

    created = client.post(
        "/api/audit-requests",
        json={"query": "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."},
    )
    request_id = created.json()["request_id"]
    client.post(f"/api/audit-requests/{request_id}/run")

    base = packaging.package_dir(request_id)
    for name in ("summary.json", "retrieval_summary.json", "validation_summary.json"):
        assert (base / name).exists(), f"{name} missing from package"

    summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    assert summary["request_id"] == request_id
    assert summary["use_case_id"] == "UC-04"
    assert summary["retry_count"] == 1
    assert summary["validation_status"] == "COMPLETE"
    assert sorted(summary["databases_searched"]) == ["DB-01", "DB-02", "DB-03", "DB-04"]
    assert summary["missing_evidence"] == []

    evidence_files = sorted(p.name for p in (base / "evidence").iterdir())
    assert evidence_files == [
        "GRN_GRN-999.pdf",
        "Invoice_INV-12345.pdf",
        "PO_PO-5678.pdf",
        "SES_SES-455.pdf",
        "Supporting_Document_01.pdf",
    ]


def test_evidence_checklist_comes_from_config_not_the_llm():
    """Required evidence resolves from YAML with no model involved."""
    from app.catalog.loader import required_evidence_for

    assert required_evidence_for("UC-04") == [
        "INVOICE",
        "PURCHASE_ORDER",
        "GRN",
        "SES",
        "SUPPORTING_DOCUMENT",
    ]
    assert required_evidence_for("UC-01")[0] == "GL_DUMP"
    assert required_evidence_for("UNKNOWN") == []


def test_review_actions_drive_status(client):
    """Approve, reject and retry each move the request appropriately."""
    query = {"query": "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."}

    approved_id = client.post("/api/audit-requests", json=query).json()["request_id"]
    client.post(f"/api/audit-requests/{approved_id}/run")
    result = client.post(
        f"/api/audit-requests/{approved_id}/review",
        json={"action": "APPROVE", "comment": "Looks good", "reviewer_name": "J. Al-Farsi"},
    ).json()
    assert result["status"] == "APPROVED"
    assert result["reviewer_name"] == "J. Al-Farsi"

    package = client.get(f"/api/audit-requests/{approved_id}/package").json()
    assert package["approved"] is True
    assert package["approved_by"] == "J. Al-Farsi"

    rejected_id = client.post("/api/audit-requests", json=query).json()["request_id"]
    client.post(f"/api/audit-requests/{rejected_id}/run")
    result = client.post(
        f"/api/audit-requests/{rejected_id}/review", json={"action": "REJECT"}
    ).json()
    assert result["status"] == "REJECTED"


def test_retry_is_bounded(run_request):
    """The retry loop cannot run forever."""
    from app.config import get_settings

    detail = run_request(
        "Provide alternate testing documents for Delta Services, Invoice INV-22222."
    )
    # SES does not exist anywhere for this vendor.
    assert detail["validation"]["validation_status"] == "NEEDS_REVIEW"
    assert detail["retry_count"] == get_settings().max_retries
    assert "SES" in detail["validation"]["missing_evidence"]


def test_evidence_file_is_served_and_confined_to_the_request(client):
    """View serves the staged file, and only for its own request."""
    query = {"query": "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."}
    first = client.post("/api/audit-requests", json=query).json()["request_id"]
    client.post(f"/api/audit-requests/{first}/run")
    detail = client.get(f"/api/audit-requests/{first}").json()
    evidence_id = detail["retrieved_evidence"][0]["evidence_id"]

    ok = client.get(f"/api/audit-requests/{first}/evidence/{evidence_id}/file")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "application/pdf"
    assert ok.content.startswith(b"%PDF")

    other = client.post("/api/audit-requests", json=query).json()["request_id"]
    leaked = client.get(f"/api/audit-requests/{other}/evidence/{evidence_id}/file")
    assert leaked.status_code == 404

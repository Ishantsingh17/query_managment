"""Audit Package Generator.

Builds final_audit_packages/{request_id}/ containing the staged evidence plus
three machine-readable summaries, so the package is traceable and
reproducible from its own contents.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.catalog.loader import enabled_databases, get_use_case
from app.config import get_settings
from app.services import repository, staging
from app.services.db import utc_now
from app.services.ordering import order_by_checklist


def package_dir(request_id: str) -> Path:
    return get_settings().final_packages_dir / request_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def generate_package(request_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Assemble the final package. Returns its summary."""
    settings = get_settings()
    request = repository.get_request(request_id) or {}
    use_case_id = state.get("use_case_id") or request.get("use_case_id") or ""
    spec = get_use_case(use_case_id)

    evidence = repository.list_retrieved_evidence(request_id)
    validation = repository.latest_validation(request_id) or {}
    attempts = repository.list_retrieval_attempts(request_id)

    base = package_dir(request_id)
    evidence_dir = base / "evidence"
    if base.exists():
        shutil.rmtree(base)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # --- copy staged evidence into the package ---------------------------
    contents: list[dict[str, Any]] = []
    for item in evidence:
        staged = staging.resolve_staged_file(request_id, item.get("staged_file_path"))
        filename = Path(item["staged_file_path"]).name if item.get("staged_file_path") else None
        copied = False
        if staged and staged.exists():
            shutil.copy2(staged, evidence_dir / staged.name)
            copied = True
            filename = staged.name

        contents.append(
            {
                "filename": filename,
                "document_id": item["document_id"],
                "document_type": item["document_type"],
                "document_type_label": spec.label_for(item["document_type"]) if spec else item["document_type"],
                "identifier": item.get("identifier"),
                "source_database_id": item["source_database_id"],
                "source_file_path": item.get("source_file_path"),
                "status": item.get("match_status"),
                "in_package": copied,
                "retrieved_at": item.get("retrieved_at"),
                "pass_number": item.get("pass_number", 1),
            }
        )

    required = list(state.get("required_evidence") or (spec.evidence_codes if spec else []))

    # Present package contents in requirement-catalog order so the manifest is
    # stable across runs rather than following whichever database answered first.
    contents = order_by_checklist(contents, required)

    found_codes = [item["document_type"] for item in evidence]
    missing = [code for code in required if code not in found_codes]

    databases_searched = sorted({attempt["database_id"] for attempt in attempts})

    # --- summary.json ----------------------------------------------------
    summary = {
        "request_id": request_id,
        "original_query": request.get("raw_query"),
        "use_case_id": use_case_id,
        "requirement_name": spec.name if spec else request.get("requirement_name"),
        "extracted_inputs": state.get("search_parameters") or {},
        "required_evidence": required,
        "found_evidence": found_codes,
        "missing_evidence": missing,
        "databases_searched": databases_searched,
        "databases_configured": [db.database_id for db in enabled_databases()],
        "validation_status": validation.get("validation_status"),
        "retry_count": state.get("retry_count", 0),
        "evidence_count": len(contents),
        "generated_at": utc_now(),
    }

    _write_json(base / "summary.json", summary)

    # --- retrieval_summary.json ------------------------------------------
    _write_json(
        base / "retrieval_summary.json",
        {
            "request_id": request_id,
            "search_parameters_final": state.get("search_context") or {},
            "discovered_identifiers": state.get("identifier_origin") or {},
            "attempts": [
                {
                    "database_id": attempt["database_id"],
                    "pass_number": attempt.get("pass_number", 1),
                    "requested_evidence": attempt.get("requested_evidence", []),
                    "search_parameters": attempt.get("search_parameters", {}),
                    "result_count": attempt.get("result_count", 0),
                    "status": attempt.get("status"),
                    "error_message": attempt.get("error_message"),
                    "started_at": attempt.get("started_at"),
                    "completed_at": attempt.get("completed_at"),
                }
                for attempt in attempts
            ],
            "evidence": contents,
            "retry_count": state.get("retry_count", 0),
            "retry_note": state.get("retry_note"),
        },
    )

    # --- validation_summary.json -----------------------------------------
    _write_json(
        base / "validation_summary.json",
        {
            "request_id": request_id,
            "validation_status": validation.get("validation_status"),
            "checks": validation.get("checks", []),
            "missing_evidence": validation.get("missing_evidence", []),
            "created_at": validation.get("created_at"),
        },
    )

    relative = str(base.relative_to(settings.data_root).as_posix())
    repository.save_package(request_id, relative, {**summary, "contents": contents})
    return {**summary, "package_path": relative, "contents": contents}

"""Validation Engine.

Deterministic checks over what was retrieved, driven by the validation_checks
declared for each use case in the Requirement Catalog. No LLM involvement and
no audit judgement: it verifies presence, document types and identifier
consistency, and defers anything requiring judgement to a human.
"""

from __future__ import annotations

from typing import Any

from app.catalog.loader import get_use_case
from app.mcp_layer.matching import nac_matches, normalize, normalize_period
from app.schemas import SearchParameters

STATUS_COMPLETE = "COMPLETE"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_ERROR = "ERROR"

RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULT_REVIEW = "REVIEW"

# Parameter name -> the evidence column it should agree with.
_PARAMETER_COLUMN = {
    "vendor_name": "vendor_name",
    "invoice_number": "invoice_number",
    "period": "period",
    "sob": "sob",
    "nac_range": "nac_code",
    "account": "account_number",
    "vendor_id": "vendor_id",
}


def _values_agree(parameter: str, expected: Any, actual: Any) -> bool:
    if parameter == "nac_range":
        return nac_matches(expected, actual)
    if parameter == "period":
        return normalize_period(expected) == normalize_period(actual)
    return normalize(expected) == normalize(actual)


def _check_parameter_match(
    parameter: str,
    label: str,
    parameters: SearchParameters,
    evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Verify retrieved evidence agrees with a stated search parameter.

    Returns None when the auditor never supplied the parameter: there is
    nothing to check against, and a request that legitimately omits an
    optional input must not be downgraded for it. Missing mandatory inputs
    are already reported through the parse ambiguities.

    Only documents that actually carry the field are examined - a purchase
    order legitimately has no NAC code, and its silence is not a mismatch.
    """
    supplied = parameters.provided()
    expected = supplied.get(parameter)
    if expected is None and parameter == "vendor_name":
        sample = parameters.vendor_sample
        expected = sample[0] if len(sample) == 1 else None

    if expected in (None, ""):
        return None

    display_label = f"{label} ({expected})"
    column = _PARAMETER_COLUMN.get(parameter, parameter)
    compared = 0
    mismatches: list[str] = []

    for item in evidence:
        metadata = item.get("metadata") or {}
        actual = metadata.get(column)
        if actual in (None, ""):
            continue
        compared += 1
        if not _values_agree(parameter, expected, actual):
            mismatches.append(f"{item.get('document_type')}={actual}")

    if compared == 0:
        return {
            "code": "PARAM_MATCH",
            "parameter": parameter,
            "label": display_label,
            "result": RESULT_REVIEW,
            "detail": "No retrieved document carries this field.",
        }
    if mismatches:
        return {
            "code": "PARAM_MATCH",
            "parameter": parameter,
            "label": display_label,
            "result": RESULT_FAIL,
            "detail": f"Mismatch on {', '.join(mismatches)}.",
        }
    return {
        "code": "PARAM_MATCH",
        "parameter": parameter,
        "label": display_label,
        "result": RESULT_PASS,
        "detail": f"Consistent across {compared} document(s).",
    }


def validate(
    use_case_id: str,
    parameters: SearchParameters,
    required_evidence: list[str],
    found_evidence: dict[str, dict[str, Any]],
    retrieved_evidence: list[dict[str, Any]],
    *,
    retries_exhausted: bool = False,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Run every configured check and derive an overall status."""
    spec = get_use_case(use_case_id)
    if spec is None:
        return {
            "validation_status": STATUS_ERROR,
            "checks": [
                {
                    "code": "CATALOG",
                    "label": "Requirement catalog resolved",
                    "result": RESULT_FAIL,
                    "detail": f"Unknown use case {use_case_id}.",
                }
            ],
            "missing_evidence": list(required_evidence),
        }

    missing = [code for code in required_evidence if code not in found_evidence]
    # Items flagged human_required cannot be closed by any amount of searching.
    human_pending = [
        code
        for code in missing
        if (requirement := spec.requirement(code)) is not None and requirement.human_required
    ]
    searchable_missing = [code for code in missing if code not in human_pending]

    checks: list[dict[str, Any]] = []

    for check in spec.validation_checks:
        if check.code == "EVIDENCE_PRESENT":
            if not missing:
                result, detail = RESULT_PASS, f"All {len(required_evidence)} items present."
            elif searchable_missing:
                result = RESULT_FAIL
                detail = "Not found: " + ", ".join(spec.label_for(c) for c in searchable_missing)
            else:
                result = RESULT_REVIEW
                detail = "Awaiting human input: " + ", ".join(
                    spec.label_for(c) for c in human_pending
                )
            checks.append(
                {"code": check.code, "label": check.label, "result": result, "detail": detail}
            )

        elif check.code == "PARAM_MATCH" and check.parameter:
            outcome = _check_parameter_match(
                check.parameter, check.label, parameters, retrieved_evidence
            )
            # None means the parameter was not supplied, so there is nothing
            # to verify and the check is omitted rather than shown as unmet.
            if outcome is not None:
                checks.append(outcome)

        elif check.code == "REPORT_TYPE_PRESENT":
            # A cost drill request names one report type but requires the AP,
            # AR and Others reports. The meaningful check is therefore that
            # the specifically requested report was retrieved, not that every
            # document shares that report type.
            requested = parameters.provided().get("report_type")
            if requested:
                expected_code = f"COST_DRILL_{str(requested).upper()}"
                if expected_code in found_evidence:
                    result = RESULT_PASS
                    detail = f"{spec.label_for(expected_code)} retrieved."
                elif expected_code in required_evidence:
                    result = RESULT_FAIL
                    detail = f"{spec.label_for(expected_code)} was not retrieved."
                else:
                    result = RESULT_REVIEW
                    detail = f"{requested} is not a recognised cost drill report type."
                checks.append(
                    {
                        "code": check.code,
                        "label": f"{check.label} ({requested})",
                        "result": result,
                        "detail": detail,
                    }
                )

        elif check.code == "DOCUMENT_TYPES":
            expected = set(required_evidence)
            actual = {item.get("document_type") for item in retrieved_evidence}
            unexpected = actual - expected
            if unexpected:
                checks.append(
                    {
                        "code": check.code,
                        "label": check.label,
                        "result": RESULT_FAIL,
                        "detail": f"Unexpected document types retrieved: {sorted(unexpected)}.",
                    }
                )
            else:
                checks.append(
                    {
                        "code": check.code,
                        "label": check.label,
                        "result": RESULT_PASS,
                        "detail": f"{len(actual)} document type(s) match the checklist.",
                    }
                )

        elif check.code == "PACKAGE_COMPLETE":
            unstaged = [
                item.get("document_type")
                for item in retrieved_evidence
                if not item.get("staged_file_path")
            ]
            if missing:
                result = RESULT_FAIL if searchable_missing else RESULT_REVIEW
                detail = f"{len(found_evidence)} of {len(required_evidence)} items staged."
            elif unstaged:
                result, detail = RESULT_FAIL, f"Not staged: {unstaged}."
            else:
                result, detail = RESULT_PASS, "Every required item is staged and traceable."
            checks.append(
                {"code": check.code, "label": check.label, "result": result, "detail": detail}
            )

    if errors:
        checks.append(
            {
                "code": "SOURCE_AVAILABILITY",
                "label": "All configured sources searched",
                "result": RESULT_REVIEW,
                "detail": "; ".join(errors),
            }
        )

    # --- overall status ---------------------------------------------------
    has_fail = any(check["result"] == RESULT_FAIL for check in checks)
    has_review = any(check["result"] == RESULT_REVIEW for check in checks)

    if not missing and not has_fail:
        status = STATUS_NEEDS_REVIEW if has_review else STATUS_COMPLETE
    elif human_pending and not searchable_missing:
        # Only human-judgement items outstanding: a person must weigh in.
        status = STATUS_NEEDS_REVIEW
    elif searchable_missing and retries_exhausted:
        status = STATUS_NEEDS_REVIEW
    else:
        status = STATUS_INCOMPLETE

    headline, message = _summarise(status, spec, missing, human_pending, searchable_missing)

    return {
        "validation_status": status,
        "checks": checks,
        "missing_evidence": missing,
        "human_pending": human_pending,
        "headline": headline,
        "message": message,
    }


def _summarise(status, spec, missing, human_pending, searchable_missing) -> tuple[str, str]:
    if status == STATUS_COMPLETE:
        return (
            "Validation Complete",
            "All evidence present and verified. Package is ready for review.",
        )
    if status == STATUS_INCOMPLETE:
        names = ", ".join(spec.label_for(code) for code in searchable_missing)
        return (
            "Validation Incomplete",
            f"Evidence still missing: {names}. A retry will search the remaining sources.",
        )
    if status == STATUS_NEEDS_REVIEW:
        if human_pending and not searchable_missing:
            names = ", ".join(spec.label_for(code) for code in human_pending)
            return (
                "Human Input Required",
                f"{names} requires human judgement and cannot be retrieved automatically.",
            )
        if searchable_missing:
            names = ", ".join(spec.label_for(code) for code in searchable_missing)
            return (
                "Needs Review",
                f"Could not locate {names} in any configured source. Reviewer decision required.",
            )
        return ("Needs Review", "Retrieved evidence requires reviewer confirmation.")
    return ("Validation Error", "Validation could not be completed.")

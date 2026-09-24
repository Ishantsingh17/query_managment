"""Validation Engine — completeness check only (additional rules plug in later via `rules`)."""
from collections.abc import Callable, Iterable

from app.core.models import ValidationResult

AVAILABLE_STATES = {"AVAILABLE", "MANUALLY_UPLOADED"}

# Future validation rules: callables (request_id, evidence_items) -> dict[evidence_type, reason]
ExtraRule = Callable[[str, list], dict[str, str]]


def validate_completeness(request_id: str, required: list[str], items: Iterable, rules: list[ExtraRule] | None = None) -> ValidationResult:
    """`items` are objects with evidence_type / validation_status / validation_reason."""
    latest = {i.evidence_type: i for i in items}
    available, missing, not_required, reasons = [], [], [], {}
    for et in required:
        item = latest.get(et)
        status = item.validation_status if item else "MISSING"
        if status in AVAILABLE_STATES:
            available.append(et)
        elif status == "NOT_REQUIRED":
            not_required.append(et)
        else:
            missing.append(et)
            reasons[et] = (item.validation_reason if item and item.validation_reason else "Evidence not retrieved")
    for rule in rules or []:
        for et, reason in rule(request_id, list(latest.values())).items():
            if et in available:
                available.remove(et)
                missing.append(et)
            reasons[et] = reason
    total = len(required) or 1
    pct = round(100 * (len(available) + len(not_required)) / total)
    return ValidationResult(request_id=request_id, required_evidence=list(required), available_evidence=available,
                            missing_evidence=missing, not_required_evidence=not_required,
                            is_complete=not missing and bool(required), reasons=reasons, completeness_pct=pct)

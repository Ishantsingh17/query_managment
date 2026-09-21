"""Evidence matching rules.

Pure functions, deliberately kept out of the MCP tool bodies so the matching
policy is independently testable.

A source row matches a search when all three hold:

  1. its document_type is one of the evidence types still being looked for;
  2. no identifier present on BOTH the row and the search context disagrees
     (this is what stops INV-99999's paperwork answering a query about
     INV-12345);
  3. at least one identifier positively agrees, so a row with nothing in
     common is never returned.

report_type is deliberately excluded from the rules. A UC-01 request names
one report type ("AP") but its checklist requires the AP, AR and Others cost
drill reports, whose types are already encoded in document_type. Filtering on
report_type would make three of the five required items unreachable.
"""

from __future__ import annotations

import re

# Identifiers precise enough to correlate documents across systems.
STRONG_IDENTIFIERS = (
    "invoice_number",
    "po_number",
    "grn_number",
    "ses_number",
    "vendor_id",
)

# Scoping filters: they narrow a population rather than identify a document.
SCOPE_FILTERS = ("period", "sob", "account_number")

# Matched case-insensitively; weaker than an id but the usual auditor input.
NAME_FILTER = "vendor_name"

_MONTHS = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "may": "may", "jun": "june", "jul": "july", "aug": "august",
    "sep": "september", "sept": "september", "oct": "october",
    "nov": "november", "dec": "december",
}

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})


def normalize(value: object) -> str | None:
    """Casefold, collapse whitespace and unify dash characters."""
    if value is None:
        return None
    text = str(value).translate(_DASHES).strip()
    if not text:
        return None
    return re.sub(r"\s+", " ", text).casefold()


def normalize_period(value: object) -> str | None:
    """Normalize a period so "Aug 2026" and "August 2026" agree."""
    text = normalize(value)
    if text is None:
        return None
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    parts = text.split(" ")
    expanded = [_MONTHS.get(part.rstrip("."), part) for part in parts]
    return " ".join(expanded)


def _parse_range(text: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if not match:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    return (low, high) if low <= high else (high, low)


def nac_matches(context_value: object, row_value: object) -> bool:
    """Compare a requested NAC range against a row's NAC code.

    Handles range-to-range equality and a single code falling inside a range,
    so "5000-5999" matches both the range-level report and NAC line 5210.
    """
    requested, actual = normalize(context_value), normalize(row_value)
    if requested is None or actual is None:
        return False
    if requested == actual:
        return True

    requested_range, actual_range = _parse_range(requested), _parse_range(actual)
    if requested_range and actual.isdigit():
        return requested_range[0] <= int(actual) <= requested_range[1]
    if actual_range and requested.isdigit():
        return actual_range[0] <= int(requested) <= actual_range[1]
    if requested_range and actual_range:
        return requested_range == actual_range
    return False


def _values_agree(key: str, context_value: object, row_value: object) -> bool:
    if key == "period":
        return normalize_period(context_value) == normalize_period(row_value)
    return normalize(context_value) == normalize(row_value)


def _context_nac(context: dict) -> object:
    return context.get("nac_range") or context.get("nac_code")


def evaluate_row(row: dict, context: dict) -> tuple[bool, list[str]]:
    """Return (matched, matched_on) for one row against a search context.

    matched_on names the fields that positively agreed, which the UI and the
    retrieval log use to explain *why* a document was picked up.
    """
    matched_on: list[str] = []

    comparable = (*STRONG_IDENTIFIERS, *SCOPE_FILTERS, NAME_FILTER)
    for key in comparable:
        context_value = context.get(key)
        row_value = row.get(key)
        if context_value in (None, "") or row_value in (None, ""):
            continue
        if _values_agree(key, context_value, row_value):
            matched_on.append(key)
        else:
            # A disagreement on a shared identifier disqualifies the row.
            return False, []

    context_nac = _context_nac(context)
    row_nac = row.get("nac_code")
    if context_nac not in (None, "") and row_nac not in (None, ""):
        if nac_matches(context_nac, row_nac):
            matched_on.append("nac_code")
        else:
            return False, []

    return bool(matched_on), matched_on


def row_matches(row: dict, required_evidence: list[str], context: dict) -> tuple[bool, list[str]]:
    """Full predicate including the evidence-type gate."""
    if required_evidence and row.get("document_type") not in required_evidence:
        return False, []
    return evaluate_row(row, context)


def harvest_identifiers(row: dict) -> dict[str, str]:
    """Pull every strong identifier off a retrieved row.

    Feeding these back into the search context is what lets a later database
    be searched with keys the original query never contained.
    """
    discovered: dict[str, str] = {}
    for key in STRONG_IDENTIFIERS:
        value = row.get(key)
        if value not in (None, ""):
            discovered[key] = str(value)
    return discovered

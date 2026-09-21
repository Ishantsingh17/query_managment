"""Deterministic rule-based query parser.

The fallback when Groq is unavailable, errors, or returns something that does
not satisfy the schema. It keeps the POC demonstrable without a network
dependency, and it never invents values: a parameter appears only when it was
literally present in the request text.
"""

from __future__ import annotations

import re

from app.catalog.loader import get_use_case
from app.schemas import ParsedQuery, SearchParameters

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)

_DASH = r"[-‐-―−]"

# Classification hints, evaluated in order. The first group that matches wins,
# so the more specific requirement is always checked before the general one.
_HINTS: list[tuple[str, tuple[str, ...]]] = [
    # "balance confirmation alternate testing" must beat plain "balance
    # confirmation", so alternate testing is tested first.
    ("UC-04", ("alternate testing", "alternate test", "alternative testing")),
    ("UC-01", ("cost drill", "expense drill")),
    # "trade payables ageing schedule" is UC-03, so trade payables is tested
    # before the generic "schedule" keyword.
    ("UC-03", ("trade payable", "aptb", "balance confirmation", "confirmation letter",
               "confirmation sample", "payable balance")),
    ("UC-02", ("schedule", "ledger extract", "opening balance", "closing balance",
               "movement", "ageing", "aging")),
]


def _search(pattern: str, text: str, group: int = 1) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(group).strip() if match else None


def extract_invoice_number(text: str) -> str | None:
    explicit = _search(
        r"invoice\s*(?:number|no\.?|#)?\s*[:\-]?\s*([A-Za-z]{2,6}" + _DASH + r"?\d{3,})", text
    )
    candidate = explicit or _search(r"\b(INV" + _DASH + r"?\d{3,})\b", text)
    if not candidate:
        return None
    # Canonicalise to PREFIX-DIGITS.
    match = re.match(r"([A-Za-z]+)" + _DASH + r"?(\d+)", candidate)
    return f"{match.group(1).upper()}-{match.group(2)}" if match else candidate.upper()


def extract_period(text: str) -> str | None:
    # "as at 30 June 2026" / "30 June 2026"
    day_first = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\s+(\d{{4}})\b", text, re.IGNORECASE
    )
    if day_first:
        return f"{int(day_first.group(1))} {day_first.group(2).title()} {day_first.group(3)}"

    # "August 2026"
    month_year = re.search(rf"\b({_MONTHS})\s+(\d{{4}})\b", text, re.IGNORECASE)
    if month_year:
        return f"{month_year.group(1).title()} {month_year.group(2)}"

    quarter = re.search(r"\b(Q[1-4])\s*(?:FY)?\s*(\d{4})\b", text, re.IGNORECASE)
    if quarter:
        return f"{quarter.group(1).upper()} {quarter.group(2)}"

    fiscal = re.search(r"\bFY\s*(\d{2,4})\b", text, re.IGNORECASE)
    if fiscal:
        return f"FY {fiscal.group(1)}"
    return None


def extract_sob(text: str) -> str | None:
    return _search(r"\bSOB\s*(?:number|no\.?|#)?\s*[:\-]?\s*(\d+)", text)


def extract_nac_range(text: str) -> str | None:
    ranged = re.search(
        r"\bNAC\s*(?:range|codes?)?\s*[:\-]?\s*(\d+)\s*(?:" + _DASH + r"|to)\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    if ranged:
        return f"{ranged.group(1)}-{ranged.group(2)}"
    # A bare range with NAC mentioned anywhere in the request.
    if re.search(r"\bNAC\b", text, re.IGNORECASE):
        bare = re.search(r"\b(\d{4})\s*(?:" + _DASH + r"|to)\s*(\d{4})\b", text)
        if bare:
            return f"{bare.group(1)}-{bare.group(2)}"
        single = _search(r"\bNAC\s*(?:code)?\s*[:\-]?\s*(\d{3,})", text)
        if single:
            return single
    return None


def extract_report_type(text: str) -> str | None:
    if re.search(r"\bothers?\b", text, re.IGNORECASE) and re.search(
        r"cost drill|expense drill", text, re.IGNORECASE
    ):
        return "OTHERS"
    match = re.search(r"\b(AP|AR)\b", text)
    return match.group(1).upper() if match else None


def extract_account(text: str) -> str | None:
    return _search(r"\baccount\s*(?:number|no\.?|code|#)?\s*[:\-]?\s*(\d{3,})", text)


_VENDOR_STOP = re.compile(
    r"\s*(?:,|\.|;|\bfor\b|\binvoice\b|\bperiod\b|\bas at\b|\bfor the\b|\bpo\b|\bgrn\b|\bses\b)",
    re.IGNORECASE,
)


# Single words that are never a vendor name on their own. Month names and
# abbreviations matter most: "for Aug 2026" must not yield a vendor of "Aug".
_MONTH_WORDS = {name for name in _MONTHS.split("|")}
_NOT_A_VENDOR = _MONTH_WORDS | {
    "invoice", "period", "account", "the", "all", "ap", "ar", "others",
    "sob", "nac", "po", "grn", "ses", "fy", "q1", "q2", "q3", "q4",
}


def extract_vendor_name(text: str) -> str | None:
    """Pull a vendor name out of 'for X', 'vendor X' or 'from X'."""
    match = re.search(
        r"\b(?:vendor|supplier|for|from)\s+([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*)*)",
        text,
    )
    if not match:
        return None

    # A capitalised token followed by a year is part of a date, not a vendor.
    if re.match(r"[A-Za-z]+\.?\s+\d{4}\b", text[match.start(1) :]):
        return None

    candidate = match.group(1).strip()
    candidate = _VENDOR_STOP.split(candidate)[0].strip(" ,.;")

    words = [w for w in candidate.split() if w]
    if not words:
        return None
    if len(words) == 1 and words[0].lower().rstrip(".") in _NOT_A_VENDOR:
        return None
    return " ".join(words)


def extract_vendor_sample(text: str) -> list[str]:
    """Read an explicit vendor list such as 'vendors A Ltd, B LLC and C Co'."""
    match = re.search(r"\bvendors?\s+([^.;]+)", text, re.IGNORECASE)
    if not match:
        return []
    segment = match.group(1)
    parts = re.split(r",|\band\b", segment, flags=re.IGNORECASE)
    names: list[str] = []
    for part in parts:
        name = part.strip(" ,.;")
        if not name or not re.match(r"^[A-Z]", name):
            continue
        name = _VENDOR_STOP.split(name)[0].strip(" ,.;")
        if name and len(name) > 1:
            names.append(name)
    return names


def classify(text: str) -> str:
    lowered = text.lower()
    for use_case_id, keywords in _HINTS:
        if any(keyword in lowered for keyword in keywords):
            return use_case_id

    # Structural fallbacks when no phrase matched.
    if extract_invoice_number(text) and (extract_vendor_name(text) or "invoice" in lowered):
        return "UC-04"
    if extract_account(text) and extract_period(text):
        return "UC-02"
    if extract_nac_range(text) or extract_sob(text):
        return "UC-01"
    return "UNSUPPORTED"


def parse(text: str) -> ParsedQuery:
    """Parse a request deterministically.

    Confidence reflects how much of the use case's mandatory input was
    actually located, so a partial parse reports itself as such rather than
    claiming certainty.
    """
    use_case_id = classify(text)
    if use_case_id == "UNSUPPORTED":
        return ParsedQuery(
            use_case_id="UNSUPPORTED",
            requirement="",
            search_parameters=SearchParameters(),
            confidence=0.0,
            ambiguities=["The request did not match any supported audit requirement."],
        )

    sample = extract_vendor_sample(text)
    vendor = extract_vendor_name(text)
    if vendor and vendor in sample:
        pass
    elif vendor and sample:
        sample = [vendor, *[s for s in sample if s != vendor]]

    parameters = SearchParameters(
        period=extract_period(text),
        sob=extract_sob(text),
        nac_range=extract_nac_range(text),
        report_type=extract_report_type(text),
        account=extract_account(text),
        vendor_name=vendor,
        invoice_number=extract_invoice_number(text),
        vendor_sample=sample,
    )

    spec = get_use_case(use_case_id)
    requirement = spec.name if spec else ""
    required = list(spec.required_parameters) if spec else []

    supplied = parameters.provided()
    satisfied = 0
    ambiguities: list[str] = []
    for key in required:
        # vendor_sample is satisfied by either an explicit list or one vendor.
        if key == "vendor_sample":
            present = bool(parameters.vendor_sample or parameters.vendor_name)
        else:
            present = key in supplied
        if present:
            satisfied += 1
        else:
            label = spec.parameter_label(key) if spec else key
            ambiguities.append(f"{label} was not found in the request.")

    ratio = (satisfied / len(required)) if required else 1.0
    confidence = round(0.60 + 0.35 * ratio, 2)

    return ParsedQuery(
        use_case_id=use_case_id,
        requirement=requirement,
        search_parameters=parameters,
        confidence=confidence,
        ambiguities=ambiguities,
    )

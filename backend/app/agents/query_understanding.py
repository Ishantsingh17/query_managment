"""Query Understanding Agent: natural language -> Structured Query + business parameters.

Does NOT decide required evidence or source systems (that is the Requirement Catalog / Registry's job).
"""
import calendar
import re
from datetime import date
from typing import Any

from observability import get_observability

from app.agents.llm import QU_COMPONENT, QU_OPERATION, llm_extract_detailed
from app.core.models import StructuredQuery

PARAM_KEYS = ("payment_document_number", "invoice_number", "po_number", "vendor_id", "employee_id", "fiscal_year",
              "period_start", "period_end")

_PATTERNS = {
    "payment_document_number": re.compile(r"\b(19\d{8})\b"),
    "po_number": re.compile(r"\b(45\d{8})\b"),
    "vendor_id": re.compile(r"\bvendor(?:\s+(?:id|number|no\.?))?\s*[:#]?\s*(\d{6,8})\b", re.I),
    "employee_id": re.compile(r"\b(E-?\d{5})\b", re.I),
    "invoice_number": re.compile(r"\b(INV-\d{4}-\d{4,6})\b", re.I),
    "fiscal_year": re.compile(r"\bFY\s*'?(20\d{2})\b", re.I),
}
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_PERIOD = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(20\d{2})\b", re.I)
_QUARTER = re.compile(r"\bQ([1-4])\s*(?:FY)?\s*(20\d{2})\b", re.I)

# Evidence mentions (used only to describe what the auditor asked for — never to decide requirements).
_EVIDENCE_MENTIONS = {
    "INVOICE": r"\binvoices?\b",
    "PO": r"\b(purchase orders?|po)\b",
    "GRN_SES": r"\b(goods receipts?|grn|ses|service entry)\b",
    "APPROVAL": r"\bapprovals?\b",
    "PAYMENT_REPORT": r"\bpayment report\b",
    "PAYMENT_ADVICE_UTR": r"\b(utr|payment advice|bank statement)\b",
    "ACCOUNTING_ENTRY": r"\baccounting entr",
    "SIGNED_CONFIRMATION_LETTER": r"\bconfirmation letter\b",
    "AGEING": r"\bage?ing\b",
    "APTB_LEDGER_EXTRACT": r"\baptb\b",
    "BOARD_RESOLUTION_LIMITS": r"\bboard resolution\b",
}


def _rules_extract(text: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, pat in _PATTERNS.items():
        m = pat.search(text)
        if m:
            val = m.group(1)
            if key == "employee_id":
                val = "E-" + val.upper().removeprefix("E").lstrip("-")
            elif key == "invoice_number":
                val = val.upper()
            params[key] = val
    m = _PERIOD.search(text)
    if m:
        month, year = _MONTHS[m.group(1).lower()], int(m.group(2))
        params["period_start"] = date(year, month, 1).isoformat()
        params["period_end"] = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    else:
        q = _QUARTER.search(text)
        if q:
            qn, year = int(q.group(1)), int(q.group(2))
            start_m, end_m = 3 * qn - 2, 3 * qn
            params["period_start"] = date(year, start_m, 1).isoformat()
            params["period_end"] = date(year, end_m, calendar.monthrange(year, end_m)[1]).isoformat()
    return params


def understand_query(text: str, known_identifiers: dict[str, Any] | None = None,
                     supported: dict[str, str] | None = None, use_llm: bool = True) -> StructuredQuery:
    """`supported` maps catalog query types to descriptions; it constrains the LLM's classification."""
    obs = get_observability()
    with obs.agent(QU_COMPONENT, operation=QU_OPERATION) as agent:
        sq, fallback_reason = _understand(text, known_identifiers, supported, use_llm)
        if fallback_reason is not None and use_llm:
            obs.log_fallback_completed(component=QU_COMPONENT, operation=QU_OPERATION, fallback_type="rules_based",
                                       reason=fallback_reason, parameter_count=len(sq.parameters))
        agent.annotate(method=sq.method, llm_used=sq.method == "llm", fallback_reason=fallback_reason,
                       parameter_names=sorted(sq.parameters), ambiguous_candidates=len(sq.ambiguous_between))
        return sq


def _understand(text: str, known_identifiers: dict[str, Any] | None, supported: dict[str, str] | None,
                use_llm: bool) -> tuple[StructuredQuery, str | None]:
    params = _rules_extract(text)
    method, confidence, llm_type, rationale, ambiguous = "rules", 0.7, None, None, []

    llm, fallback_reason = llm_extract_detailed(text, supported) if use_llm else (None, "llm_not_requested")
    if llm is not None:
        method, confidence, llm_type, rationale = "llm", 0.9, llm.query_type, llm.classification_rationale or None
        ambiguous = [q for q in (llm.ambiguous_between or []) if not supported or q in supported]
        for key in PARAM_KEYS:
            val = getattr(llm, key)
            # Controlled output: only accept identifiers that literally occur in the request text.
            if val and (key.startswith("period") or str(val) in text):
                params.setdefault(key, val)

    # Auditor-entered identifiers are authoritative.
    for key, val in (known_identifiers or {}).items():
        if val not in (None, ""):
            params[key] = str(val).strip()

    mentions = [et for et, pat in _EVIDENCE_MENTIONS.items() if re.search(pat, text, re.I)]
    sq = StructuredQuery(query_type=llm_type, parameters=params, source_text=text,
                         requested_evidence=mentions, confidence=confidence, method=method, rationale=rationale,
                         ambiguous_between=ambiguous if len(ambiguous) > 1 else [])
    return sq, fallback_reason

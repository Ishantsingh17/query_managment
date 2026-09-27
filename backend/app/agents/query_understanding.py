"""Query Understanding Agent: natural language -> Structured Query + business parameters.

Does NOT decide required evidence or source systems (that is the Requirement Catalog / Registry's job).
"""
import re
from typing import Any

from observability import get_observability

from app.agents.llm import QU_COMPONENT, QU_OPERATION, llm_extract
from app.core.models import StructuredQuery

PARAM_KEYS = ("payment_document_number", "invoice_number", "po_number", "vendor_id", "employee_id", "fiscal_year",
              "period_start", "period_end")

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


def understand_query(text: str, known_identifiers: dict[str, Any] | None = None,
                     supported: dict[str, str] | None = None) -> StructuredQuery:
    """`supported` maps catalog query types to descriptions; it constrains the LLM's classification.
    Raises LlmUnavailableError when the LLM fails (recorded on this agent span and its llm_call span)."""
    obs = get_observability()
    with obs.agent(QU_COMPONENT, operation=QU_OPERATION) as agent:
        sq = _understand(text, known_identifiers, supported)
        agent.annotate(method=sq.method, llm_used=True, parameter_names=sorted(sq.parameters),
                       ambiguous_candidates=len(sq.ambiguous_between))
        return sq


def _understand(text: str, known_identifiers: dict[str, Any] | None,
                supported: dict[str, str] | None) -> StructuredQuery:
    llm = llm_extract(text, supported)
    llm_type, rationale = llm.query_type, llm.classification_rationale or None
    ambiguous = [q for q in (llm.ambiguous_between or []) if not supported or q in supported]
    params: dict[str, Any] = {}
    for key in PARAM_KEYS:
        val = getattr(llm, key)
        # Controlled output: only accept identifiers that literally occur in the request text (any letter case).
        if val and (key.startswith("period") or str(val).lower() in text.lower()):
            params[key] = val

    # Auditor-entered identifiers are authoritative.
    for key, val in (known_identifiers or {}).items():
        if val not in (None, ""):
            params[key] = str(val).strip()

    mentions = [et for et, pat in _EVIDENCE_MENTIONS.items() if re.search(pat, text, re.I)]
    return StructuredQuery(query_type=llm_type, parameters=params, source_text=text,
                           requested_evidence=mentions, confidence=0.9, method="llm", rationale=rationale,
                           ambiguous_between=ambiguous if len(ambiguous) > 1 else [])

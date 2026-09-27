"""Deterministic stand-in for the LLM, used only by tests (the app has no rules-based mode; tests must not call a
real provider). It answers the Query Understanding structured-output call from simple patterns and the stakeholder
classification keywords, and ends agentic retrieval immediately so the deterministic executor runs the plan."""
import calendar
import re
from datetime import date

from langchain_core.messages import AIMessage

from app.db.stakeholder_config import QUERY_TYPE_DEFINITIONS

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
_KEYWORDS = {qt: [(p.rsplit("=", 1)[0].strip().lower(), int(p.rsplit("=", 1)[1])) for p in kw.split(";") if "=" in p]
             for qt, _, _, _, kw in QUERY_TYPE_DEFINITIONS}


def extract(text: str, supported: list[str]) -> dict:
    out: dict = {}
    for key, pat in _PATTERNS.items():
        m = pat.search(text)
        if m:
            val = m.group(1)
            if key == "employee_id":
                val = "E-" + val.upper().removeprefix("E").lstrip("-")
            elif key == "invoice_number":
                val = val.upper()
            out[key] = val
    m, q = _PERIOD.search(text), _QUARTER.search(text)
    if m:
        month, year = _MONTHS[m.group(1).lower()], int(m.group(2))
        out["period_start"] = date(year, month, 1).isoformat()
        out["period_end"] = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    elif q:
        qn, year = int(q.group(1)), int(q.group(2))
        out["period_start"] = date(year, 3 * qn - 2, 1).isoformat()
        out["period_end"] = date(year, 3 * qn, calendar.monthrange(year, 3 * qn)[1]).isoformat()

    lower = text.lower()
    scores = []
    for qt in supported:
        score = 0
        for phrase, weight in _KEYWORDS.get(qt, []):
            if phrase.startswith("param:"):
                score += weight if out.get(phrase.removeprefix("param:")) else 0
            elif re.search(r"(?<![a-z])" + re.escape(phrase), lower):
                score += weight
        scores.append((score, qt))
    scores.sort(reverse=True)
    if scores and scores[0][0] >= 3:
        close = [qt for sc, qt in scores if sc >= 3 and scores[0][0] - sc < 2]
        out["query_type"] = scores[0][1]
        if len(close) > 1:
            out["ambiguous_between"] = close
    return out


class FakeLLM:
    """Plain object with the two chat-model entry points the app uses."""

    def with_structured_output(self, schema):
        class _Structured:
            def invoke(self, messages):
                system, human = messages[0][1], messages[-1][1]
                supported = re.findall(r"^- ([A-Z_]+):", system, re.M)
                return schema(**extract(human, supported))
        return _Structured()

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return AIMessage("Leaving the retrieval plan to the deterministic executor.")

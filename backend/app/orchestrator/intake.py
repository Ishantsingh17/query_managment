"""Request intake: natural language -> Structured Query -> Query Type -> required evidence -> required parameters.

Produces the "Request Understanding" shown to the auditor and decides whether retrieval may start:
  READY                  query type identified and every mandatory retrieval parameter present
  WAITING_FOR_PARAMETERS query type identified, but a parameter must be supplied (asked conversationally)
  NEEDS_CLARIFICATION    request matches more than one supported query type
  UNSUPPORTED            request does not match a supported query type
Everything is derived from the SQLite configuration (definitions, catalog, registry) — nothing is hard-coded.
"""
import hashlib
import json
import time
from calendar import month_name
from datetime import date
from typing import Any

from observability import get_observability
from sqlalchemy.orm import Session

from app.agents.classification import classify_query
from app.agents.query_understanding import understand_query
from app.core.labels import query_type_label
from app.core.models import StructuredQuery
from app.registry.resolution import (analyze_parameters, query_type_catalog, query_type_definitions,
                                     resolve_requirements, resolve_source_mappings)

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600  # seconds — lets "Start retrieval" reuse the analysis (and its LLM call) the auditor just saw

PARAM_LABELS = {
    "payment_document_number": "Payment Document Number", "invoice_number": "Invoice Number", "po_number": "PO Number",
    "vendor_id": "Vendor ID", "employee_id": "Employee ID", "fiscal_year": "Fiscal Year",
    "period_start": "Period start", "period_end": "Period end",
}


def _period_text(params: dict) -> str | None:
    start, end = params.get("period_start"), params.get("period_end")
    if not start:
        return None
    try:
        s = date.fromisoformat(str(start))
        e = date.fromisoformat(str(end)) if end else None
    except ValueError:
        return str(start)
    if e and s.day == 1 and s.year == e.year and s.month == e.month:
        return f"{month_name[s.month]} {s.year}"
    return f"{s.isoformat()} – {e.isoformat()}" if e else s.isoformat()


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def analyze_request(session: Session, query: str, identifiers: dict[str, Any], user_query_type: str | None) -> dict:
    """Raises LlmUnavailableError (HTTP 503 with a user-facing message) when the LLM fails; nothing is cached then."""
    key = hashlib.sha256(json.dumps([query.strip(), identifiers, user_query_type],
                                    sort_keys=True).encode()).hexdigest()
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]

    definitions = query_type_definitions(session)
    sq = understand_query(query, identifiers, query_type_catalog(session))
    c = classify_query(sq, definitions, user_query_type or None)
    params = {k: v for k, v in sq.parameters.items() if v not in (None, "")}
    period = _period_text(params)

    out: dict[str, Any] = {
        "query_type": c.query_type, "query_type_label": query_type_label(c.query_type) if c.query_type else None,
        "classification_status": c.status, "confidence": c.confidence, "method": c.method,
        "rationale": sq.rationale if c.method == "llm" else None,
        "candidates": [{"value": q, "label": definitions[q].display_name} for q in c.candidates],
        "supported_query_types": [{"value": q, "label": d.display_name} for q, d in definitions.items()],
        "parameters": [{"param": k, "label": PARAM_LABELS.get(k, k.replace("_", " ").title()), "value": str(v)}
                       for k, v in params.items()],
        "period": period,
        "evidence_requested": [], "required_parameters": [], "missing_parameters": [],
        "parameter_status": "NOT_APPLICABLE",
    }

    if c.status == "identified":
        reqs = resolve_requirements(session, c.query_type)
        maps = resolve_source_mappings(session, [r.evidence_type for r in reqs])
        pa = analyze_parameters(reqs, maps, params)
        out["evidence_requested"] = [{**e, "description": r.evidence_description}
                                     for e, r in zip(pa["evidence"], reqs)]
        out["required_parameters"] = pa["required_parameters"]
        out["missing_parameters"] = pa["missing_parameters"]
        out["parameter_status"] = "ACTION_REQUIRED" if pa["missing_parameters"] else "COMPLETE"
        label = out["query_type_label"] + (f" for {period}" if period else "")
        if pa["missing_parameters"]:
            asks = [m["label"] + (" (or " + " / ".join(a["label"] for a in m["alternatives"]) + ")" if m["alternatives"] else "")
                    for m in pa["missing_parameters"]]
            out["retrieval_status"] = "WAITING_FOR_PARAMETERS"
            out["message"] = f"I understood this as {label}, but I need the {_join(asks)} to continue."
        else:
            given = [f"{p['label']} {p['value']}" for p in pa["required_parameters"] if p["satisfied"]]
            out["retrieval_status"] = "READY"
            out["message"] = (f"I understood this as {label}" + (f" ({_join(given)})" if given else "") +
                              f". All required details are present — ready to retrieve {len(reqs)} evidence items.")
    elif c.status == "ambiguous":
        out["retrieval_status"] = "NEEDS_CLARIFICATION"
        out["message"] = ("This request could match " + _join([x["label"] for x in out["candidates"]]) +
                          ". Which one do you need?")
    else:
        out["retrieval_status"] = "UNSUPPORTED"
        names = _join([d.display_name for d in definitions.values()])
        out["message"] = ("That Query Type isn't available. " if c.status == "invalid_selection" else
                          "This request doesn't match a Query Type that is currently supported. ") + \
                         f"Supported Query Types are: {names}."

    out["_structured_query"] = StructuredQuery(**{**sq.model_dump(), "query_type": c.query_type}).model_dump()
    out["_observability_trace_id"] = get_observability().current_trace_id()  # lets a later request link this analysis
    _CACHE[key] = (time.time(), out)
    if len(_CACHE) > 500:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:250]:
            _CACHE.pop(k, None)
    return out


def clear_cache() -> None:
    _CACHE.clear()


def public(understanding: dict) -> dict:
    return {k: v for k, v in understanding.items() if not k.startswith("_")}

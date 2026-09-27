"""Query Type Classification against the stakeholder Query Type Definitions (SQLite configuration).

No Query Type knowledge lives in code: the supported types come from `query_type_definitions`. The query type
itself is chosen by the Query Understanding LLM (constrained to those types); there is no keyword/rules scoring.
Outcomes: identified | ambiguous | unsupported | invalid_selection.
"""
from dataclasses import dataclass, field

from observability import get_observability

from app.core.models import StructuredQuery
from app.registry.resolution import QueryTypeDef


@dataclass
class Classification:
    query_type: str | None
    status: str  # identified | ambiguous | unsupported | invalid_selection
    confidence: float = 0.0
    method: str = "llm"
    candidates: list[str] = field(default_factory=list)


def classify_query(sq: StructuredQuery, definitions: dict[str, QueryTypeDef],
                   user_selected: str | None = None) -> Classification:
    # Deterministic step: never an LLM call itself — the type comes from the Query Understanding LLM output.
    with get_observability().agent("query_type_classification", operation="query_type_classification") as agent:
        c = _classify(sq, definitions, user_selected)
        agent.annotate(status=c.status, method=c.method, llm_used=False, candidate_count=len(c.candidates),
                       classification_source="query_understanding_llm" if c.method == "llm" else c.method)
        return c


def _classify(sq: StructuredQuery, definitions: dict[str, QueryTypeDef], user_selected: str | None) -> Classification:
    if user_selected:
        if user_selected in definitions:
            return Classification(user_selected, "identified", 1.0, "user_selected")
        return Classification(None, "invalid_selection")
    if len(sq.ambiguous_between) > 1 and all(q in definitions for q in sq.ambiguous_between):
        return Classification(None, "ambiguous", 0.0, sq.method, list(sq.ambiguous_between))
    if sq.query_type in definitions:
        return Classification(sq.query_type, "identified", sq.confidence, sq.method)
    return Classification(None, "unsupported", 0.0, sq.method)

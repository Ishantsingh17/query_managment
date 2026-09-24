"""Query Type Classification against the stakeholder Query Type Definitions (SQLite configuration).

No Query Type knowledge lives in code: supported types, display names and classification keywords all come
from `query_type_definitions`. Outcomes: identified | ambiguous | unsupported | invalid_selection.
"""
import re
from dataclasses import dataclass, field

from observability import get_observability

from app.core.models import StructuredQuery
from app.registry.resolution import QueryTypeDef

MIN_SCORE = 3      # below this nothing is identified -> unsupported
AMBIGUITY_GAP = 2  # top two candidates closer than this -> ask the auditor


@dataclass
class Classification:
    query_type: str | None
    status: str  # identified | ambiguous | unsupported | invalid_selection
    confidence: float = 0.0
    method: str = "rules"
    candidates: list[str] = field(default_factory=list)


def _score(sq: StructuredQuery, d: QueryTypeDef) -> int:
    text = sq.source_text.lower()
    score = 0
    for phrase, weight in d.keywords:
        if phrase.startswith("param:"):
            score += weight if sq.parameters.get(phrase.removeprefix("param:")) else 0
        elif re.search(r"(?<![a-z])" + re.escape(phrase), text):
            score += weight
    return score


def classify_query(sq: StructuredQuery, definitions: dict[str, QueryTypeDef],
                   user_selected: str | None = None) -> Classification:
    # Deterministic step: never an LLM call. When method == "llm" the type came from the Query Understanding LLM output.
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

    scores = sorted(((_score(sq, d), qt) for qt, d in definitions.items()), reverse=True)
    if not scores or scores[0][0] < MIN_SCORE:
        return Classification(None, "unsupported")
    top, best = scores[0]
    close = [qt for sc, qt in scores if sc >= MIN_SCORE and top - sc < AMBIGUITY_GAP]
    if len(close) > 1:
        return Classification(None, "ambiguous", 0.0, "rules", close)
    total = sum(sc for sc, _ in scores) or 1
    return Classification(best, "identified", round(top / total, 2), "rules")

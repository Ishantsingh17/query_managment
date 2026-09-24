"""Deterministic lookups against the SQLite configuration tables (Query Type Definitions, Requirement Catalog,
Evidence Source Registry). Agents never invent required evidence, source mappings or key dependencies —
they come only from here.

Search / Retrieval Keys grammar (registry column, see app/db/stakeholder_config.py):
    "A / B"                     either key identifies the record (alternatives)
    "A, B"                      both keys are required
    "PO Number [from INVOICE]"  value from the request, or from the retrieved INVOICE record (documented dependency)
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.labels import evidence_label, set_query_type_labels
from app.core.models import EvidenceSourceMapping, KeyRef, RequirementItem
from app.db.models import EvidenceSourceRegistry, QueryTypeDefinition, RequirementCatalog


def key_to_param(key_label: str) -> str:
    """'Payment Document Number' -> 'payment_document_number'; 'PO Number' -> 'po_number'."""
    return re.sub(r"[^a-z0-9]+", "_", key_label.strip().lower()).strip("_")


_DERIVED = re.compile(r"^(?P<label>.+?)\s*\[\s*from\s+(?P<src>[A-Z0-9_]+)\s*\]$", re.I)


def parse_keys(spec: str) -> list[list[KeyRef]]:
    """Parse the Search / Retrieval Keys column into AND-groups of alternative keys."""
    groups: list[list[KeyRef]] = []
    for group in re.split(r"[,+;]", spec or ""):
        alts = []
        for alt in re.split(r"\s*/\s*|\s+or\s+", group.strip()):
            alt = alt.strip()
            if not alt:
                continue
            m = _DERIVED.match(alt)
            label = m.group("label").strip() if m else alt
            alts.append(KeyRef(param=key_to_param(label), label=label,
                               derived_from=m.group("src").upper() if m else None))
        if alts:
            groups.append(alts)
    return groups


# ---- Query Type Definitions ---------------------------------------------------------------------

@dataclass
class QueryTypeDef:
    query_type: str
    display_name: str
    evidence_required: str
    automation_behavior: str
    keywords: list[tuple[str, int]] = field(default_factory=list)


def _parse_keywords(raw: str) -> list[tuple[str, int]]:
    out = []
    for part in (raw or "").split(";"):
        if "=" in part:
            phrase, weight = part.rsplit("=", 1)
            try:
                out.append((phrase.strip().lower(), int(weight)))
            except ValueError:
                continue
    return out


def query_type_definitions(session: Session) -> dict[str, QueryTypeDef]:
    """Definitions for Query Types that have Requirement Catalog rows (only those are supported)."""
    catalog_types = set(session.scalars(select(RequirementCatalog.query_type).distinct()))
    out = {}
    for d in session.scalars(select(QueryTypeDefinition).order_by(QueryTypeDefinition.query_type)):
        if d.query_type in catalog_types:
            out[d.query_type] = QueryTypeDef(d.query_type, d.display_name, d.evidence_required,
                                             d.automation_behavior, _parse_keywords(d.classification_keywords))
    return out


def supported_query_types(session: Session) -> set[str]:
    return set(query_type_definitions(session))


def query_type_catalog(session: Session) -> dict[str, str]:
    """Query type -> description (context for LLM classification), from the stakeholder definitions."""
    return {qt: f"{d.display_name}. Evidence required: {d.evidence_required}. Automation: {d.automation_behavior}"
            for qt, d in query_type_definitions(session).items()}


def refresh_label_cache(session: Session) -> None:
    set_query_type_labels({d.query_type: d.display_name for d in session.scalars(select(QueryTypeDefinition))})


# ---- Requirement Catalog / Evidence Source Registry ----------------------------------------------

def resolve_requirements(session: Session, query_type: str) -> list[RequirementItem]:
    rows = session.scalars(select(RequirementCatalog).where(RequirementCatalog.query_type == query_type)
                           .order_by(RequirementCatalog.requirement_id))
    return [RequirementItem(requirement_id=r.requirement_id, query_type=r.query_type,
                            evidence_type=r.evidence_type, evidence_description=r.evidence_description) for r in rows]


def resolve_source_mappings(session: Session, evidence_types: list[str]) -> dict[str, list[EvidenceSourceMapping]]:
    rows = session.scalars(select(EvidenceSourceRegistry).where(EvidenceSourceRegistry.evidence_type.in_(evidence_types)))
    out: dict[str, list[EvidenceSourceMapping]] = {et: [] for et in evidence_types}
    for r in rows:
        groups = parse_keys(r.search_retrieval_keys)
        out[r.evidence_type].append(EvidenceSourceMapping(
            evidence_type=r.evidence_type, source_system=r.source_system,
            source_usage_rule=r.source_usage_selection_rule, retrieval_method=r.retrieval_method,
            retrieval_keys=[k.label for g in groups for k in g], key_groups=groups,
            source_object_location=r.source_object_location, expected_output_type=r.expected_output_type,
        ))
    return out


def endpoint_path(location: str | None) -> str | None:
    """'GROSS Invoice API - GET /invoices' -> '/invoices'."""
    if not location:
        return None
    m = re.search(r"(?:GET|POST)\s+(/\S+)", location)
    return m.group(1) if m else None


# ---- Required parameter analysis ------------------------------------------------------------------

def analyze_parameters(requirements: list[RequirementItem], mappings: dict[str, list[EvidenceSourceMapping]],
                       params: dict) -> dict:
    """Work out which request parameters the configured retrieval needs, which are present, and which to ask for.

    An evidence type is retrievable when every key group of its primary mapping(s) is satisfied by a request
    parameter or by a documented dependency on another retrievable evidence type in the same request.
    """
    required = [r.evidence_type for r in requirements]
    have = {k for k, v in params.items() if v not in (None, "")}

    def primary(et):
        maps = mappings.get(et, [])
        return [m for m in maps if m.role == "primary"] or [m for m in maps if m.role != "corroborating"]

    def group_ok(group, retrievable):
        return any(k.param in have or (k.derived_from and k.derived_from in retrievable) for k in group)

    def et_ok(et, retrievable):
        return any(all(group_ok(g, retrievable) for g in m.key_groups) for m in primary(et))

    retrievable: set[str] = set()
    changed = True
    while changed:
        changed = False
        for et in required:
            if et not in retrievable and et_ok(et, retrievable):
                retrievable.add(et)
                changed = True

    # Root (user-suppliable) key groups across the plan, for display.
    labels: dict[str, str] = {}
    root_groups: list[list[KeyRef]] = []
    for et in required:
        for m in primary(et):
            for g in m.key_groups:
                roots = [k for k in g if not k.derived_from]
                for k in g:
                    labels.setdefault(k.param, k.label)
                if roots and not any(k.derived_from in required for k in g if k.derived_from):
                    if not any({k.param for k in r} == {k.param for k in roots} for r in root_groups):
                        root_groups.append(roots)

    # Greedy choice of parameters to ask for: the key that unblocks the most evidence types first.
    unmet: dict[str, list[list[KeyRef]]] = {}
    for et in required:
        if et in retrievable:
            continue
        m = (primary(et) or [None])[0]
        if m is None:
            continue
        unmet[et] = [[k for k in g if not k.derived_from] for g in m.key_groups if not group_ok(g, retrievable)]
    ask: list[dict] = []
    hypothetical = set(have)
    while True:
        counts: dict[str, int] = {}
        for groups in unmet.values():
            for g in groups:
                if not any(k.param in hypothetical for k in g):
                    for k in g:
                        counts[k.param] = counts.get(k.param, 0) + 1
        if not counts:
            break
        best = max(counts, key=lambda p: counts[p])
        hypothetical.add(best)
        # Offer an alternative only if it unblocks every group the chosen key unblocks.
        best_groups = [{k.param for k in g} for groups in unmet.values() for g in groups if best in {x.param for x in g}]
        alts = sorted(set.intersection(*best_groups) - {best}) if best_groups else []
        ask.append({"param": best, "label": labels.get(best, best), "alternatives": [
            {"param": a, "label": labels.get(a, a)} for a in alts]})

    # A group that is a superset of another is implied by it ("A or B" is satisfied whenever "A" is).
    root_groups = [g for g in root_groups
                   if not any({k.param for k in h} < {k.param for k in g} for h in root_groups)]
    required_parameters = [{
        "params": [k.param for k in g], "label": " or ".join(k.label for k in g),
        "satisfied": any(k.param in have for k in g),
        "value": next((str(params[k.param]) for k in g if k.param in have), None),
    } for g in root_groups]
    return {
        "retrievable": [et for et in required if et in retrievable],
        "blocked": [et for et in required if et not in retrievable],
        "required_parameters": required_parameters,
        "missing_parameters": ask,
        "labels": labels,
        "evidence": [{"evidence_type": et, "label": evidence_label(et)} for et in required],
    }

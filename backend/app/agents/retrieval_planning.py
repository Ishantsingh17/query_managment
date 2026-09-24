"""Retrieval Planning: builds a source-aware plan from required evidence + registry mappings.
No direct database/API access to sources."""
from typing import Any

from observability import get_observability

from app.core.models import EvidenceSourceMapping, RequirementItem, RetrievalPlan
from app.registry.resolution import endpoint_path

_ROLE_ORDER = {"primary": 0, "alternative": 1, "corroborating": 2}


def build_plan(request_id: str, requirements: list[RequirementItem],
               mappings: dict[str, list[EvidenceSourceMapping]], parameters: dict[str, Any]) -> list[RetrievalPlan]:
    with get_observability().agent("retrieval_planning", operation="build_retrieval_plan") as agent:
        plan = _build(request_id, requirements, mappings, parameters)
        agent.annotate(llm_used=False, requirement_count=len(requirements), plan_steps=len(plan),
                       source_systems=sorted({p.source_system for p in plan}))
        return plan


def _build(request_id: str, requirements: list[RequirementItem], mappings: dict[str, list[EvidenceSourceMapping]],
           parameters: dict[str, Any]) -> list[RetrievalPlan]:
    plan: list[RetrievalPlan] = []
    for req in requirements:
        for m in sorted(mappings.get(req.evidence_type, []), key=lambda m: _ROLE_ORDER[m.role]):
            if m.retrieval_method.upper() not in ("API", "APIS"):
                continue  # current design: API retrieval only
            groups = [[k.param for k in g] for g in m.key_groups]
            key_names = [p for g in groups for p in g]
            derived = {k.param: k.derived_from for g in m.key_groups for k in g if k.derived_from}
            plan.append(RetrievalPlan(
                request_id=request_id, evidence_type=req.evidence_type, source_system=m.source_system,
                method="API", keys={k: parameters.get(k) for k in key_names}, key_names=key_names,
                key_groups=groups, derived=derived,
                endpoint=endpoint_path(m.source_object_location), expected_output_type=m.expected_output_type,
                role=m.role,
            ))
    return plan

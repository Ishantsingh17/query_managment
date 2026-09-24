"""Orchestrator state graph (LangGraph).

full  : understand -> classify -> resolve_requirements -> resolve_sources -> plan -> retrieve -> process
        -> validate -> {complete: review_package -> notify_sme | incomplete: rework}
retry : resolve_requirements -> resolve_sources -> plan(targets) -> retrieve -> process -> validate -> validation_pending

Every node returns structured output into the request context; durable state is written to the Request DB.
Observability: one workflow span per run (correlated by request id); agent steps are spans; deterministic
plumbing nodes (registry/catalog lookups) are intentionally not instrumented to keep traces readable.
"""
import json
import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from observability import get_observability
from observability.integrations.langgraph import graph_config, observe_node

from app.agents.classification import classify_query
from app.agents.query_understanding import understand_query
from app.agents.llm_retrieval_agent import AgenticRetrievalAgent
from app.agents.retrieval_agent import RawEvidence
from app.agents.retrieval_planning import build_plan
from app.core.labels import evidence_label, query_type_label
from app.core.models import EvidenceSourceMapping, RequirementItem, RetrievalPlan, StructuredQuery, ValidationResult
from app.db.models import EvidenceItem
from app.db.session import session_scope
from app.evidence.normalization import new_evidence_id, normalize
from app.mcp.gateway import get_gateway
from app.orchestrator import persistence as db
from app.registry.resolution import (query_type_catalog, query_type_definitions, resolve_requirements,
                                     resolve_source_mappings)
from app.validation.engine import validate_completeness

log = logging.getLogger(__name__)
SYSTEM = {"actor_name": "Retrieval service", "actor_role": "System"}


class WorkflowState(TypedDict, total=False):
    request_id: str
    mode: Literal["full", "retry"]
    target_evidence: list[str] | None
    structured_query: StructuredQuery
    query_type: str | None
    requirements: list[RequirementItem]
    mappings: dict[str, list[EvidenceSourceMapping]]
    plan: list[RetrievalPlan]
    raw: list[RawEvidence]
    warnings: list[str]
    validation: ValidationResult
    halted: bool


# ---- nodes ------------------------------------------------------------------------------------

def understand(state: WorkflowState) -> dict[str, Any]:
    rid = state["request_id"]
    with session_scope() as s:
        r = db.get_request(s, rid)
        db.set_status(s, r, "PROCESSING")
        intake = json.loads(r.structured_query_json or "{}")
        if intake.get("precomputed"):  # understanding already ran (LLM) at submission; reuse, don't re-call
            with get_observability().agent("query_understanding_agent", operation="reuse_intake_analysis") as agent:
                sq = StructuredQuery(**intake["precomputed"])
                agent.annotate(llm_used=False, reused_intake_result=True, intake_method=sq.method)
        else:
            sq = understand_query(r.original_query, intake.get("known_identifiers"), query_type_catalog(s))
        r.structured_query_json = json.dumps({**sq.model_dump(), "known_identifiers": intake.get("known_identifiers", {}),
                                              "user_selected_query_type": intake.get("user_selected_query_type")})
    return {"structured_query": sq}


def classify_node(state: WorkflowState) -> dict[str, Any]:
    rid, sq = state["request_id"], state["structured_query"]
    with session_scope() as s:
        r = db.get_request(s, rid)
        intake = json.loads(r.structured_query_json or "{}")
        c = classify_query(sq, query_type_definitions(s), intake.get("user_selected_query_type"))
        qt, conf, method = c.query_type, c.confidence, c.method
        rationale = f" {sq.rationale}" if method == "llm" and sq.rationale else ""
        if qt is None:
            db.set_status(s, r, "REWORK_REQUIRED")
            r.validation_status = "UNCLASSIFIED"
            db.add_event(s, rid, "Processing", "warning", "Query type could not be determined",
                         "Please resubmit with a Query type selected.", **SYSTEM)
            return {"halted": True, "query_type": None}
        r.query_type = qt
        data = json.loads(r.structured_query_json)
        data.update(query_type=qt, classification={"confidence": conf, "method": method, "rationale": sq.rationale})
        r.structured_query_json = json.dumps(data)
        db.add_event(s, rid, "Processing", "progress", "Processing started",
                     f"Query classified as {query_type_label(qt)}.{rationale}", **SYSTEM)
    return {"query_type": qt, "halted": False}


def load_context(state: WorkflowState) -> dict[str, Any]:
    """Retry entry: reload structured query + query type from the Request DB."""
    with session_scope() as s:
        r = db.get_request(s, state["request_id"])
        data = json.loads(r.structured_query_json or "{}")
        sq = StructuredQuery(**{k: data[k] for k in StructuredQuery.model_fields if k in data})
        return {"structured_query": sq, "query_type": r.query_type, "halted": False}


def resolve_requirements_node(state: WorkflowState) -> dict[str, Any]:
    with session_scope() as s:
        return {"requirements": resolve_requirements(s, state["query_type"])}


def resolve_sources_node(state: WorkflowState) -> dict[str, Any]:
    with session_scope() as s:
        return {"mappings": resolve_source_mappings(s, [r.evidence_type for r in state["requirements"]])}


def plan_node(state: WorkflowState) -> dict[str, Any]:
    reqs = state["requirements"]
    params = dict(state["structured_query"].parameters)
    targets = state.get("target_evidence")
    if targets:
        # Retry: documented dependencies ("[from X]") may be satisfied by evidence already retrieved earlier.
        derived = {k.param: k.derived_from for r in reqs if r.evidence_type in targets
                   for m in state["mappings"].get(r.evidence_type, []) for g in m.key_groups for k in g if k.derived_from}
        if derived:
            with session_scope() as s:
                items = {i.evidence_type: i for i in db.items_for(s, state["request_id"])}
            for param, source_type in derived.items():
                item = items.get(source_type)
                if item is not None and item.validation_status == "AVAILABLE" and item.normalized_payload_json:
                    record = json.loads(item.normalized_payload_json).get("normalized_payload", {}).get("record", {})
                    if record.get(param) not in (None, ""):
                        params.setdefault(param, str(record[param]))
        reqs = [r for r in reqs if r.evidence_type in targets]
    sq = state["structured_query"].model_copy(update={"parameters": params})
    return {"plan": build_plan(state["request_id"], reqs, state["mappings"], params), "structured_query": sq}


def retrieve_node(state: WorkflowState) -> dict[str, Any]:
    raw, warnings = AgenticRetrievalAgent(get_gateway()).execute(state["plan"], state["structured_query"].parameters)
    return {"raw": raw, "warnings": warnings}


def process_node(state: WorkflowState) -> dict[str, Any]:
    rid = state["request_id"]
    with session_scope() as s:
        for raw in state["raw"]:
            label = evidence_label(raw.evidence_type)
            if raw.found:
                ev = normalize(rid, raw)
                db.replace_item(s, rid, raw.evidence_type, db.item_from_canonical(ev))
                verb = "matched in" if raw.evidence_type == "PO" else "retrieved from"
                db.add_event(s, rid, "Processing", "success", f"{label} {verb} {ev.source_system}",
                             f"{ev.source_reference} · {ev.metadata.get('description')}", **SYSTEM)
                for note in raw.notes:
                    db.add_event(s, rid, "Processing", "warning", note, None, **SYSTEM)
            else:
                src = raw.step.source_system if raw.step else raw.planned_source
                item = EvidenceItem(evidence_id=new_evidence_id(), request_id=rid, evidence_type=raw.evidence_type,
                                    source_system=src, source_reference=None, retrieval_method="API",
                                    payload_type=None, file_path=None,
                                    normalized_payload_json=json.dumps({"metadata": {"attempts": raw.attempts,
                                                                                     "source_error": raw.source_error}}),
                                    validation_status="MISSING", validation_reason=raw.reason, is_approved=False)
                db.replace_item(s, rid, raw.evidence_type, item)
                db.add_event(s, rid, "Processing", "warning", f"{label} missing in {src}", raw.reason, **SYSTEM)

        found = [r for r in state["raw"] if r.found]
        sources = sorted({r.result.source_system for r in found if r.result})
        src_text = (", ".join(sources[:-1]) + " and " + sources[-1]) if len(sources) > 1 else (sources[0] if sources else "no sources")
        db.add_event(s, rid, "Processing", "success" if len(found) == len(state["raw"]) else "info",
                     "Processing completed" if state.get("mode") == "full" else "Retry completed",
                     f"{len(found)} of {len(state['raw'])} evidence items retrieved from {src_text}.", **SYSTEM)
    return {}


def validate_node(state: WorkflowState) -> dict[str, Any]:
    rid = state["request_id"]
    with session_scope() as s:
        r = db.get_request(s, rid)
        required = [q.evidence_type for q in state["requirements"]]
        result = validate_completeness(rid, required, db.items_for(s, rid))
        get_observability().log_validation("completeness_check", component="completeness_validation",
                                           outcome="complete" if result.is_complete else "incomplete", llm_used=False,
                                           required=len(result.required_evidence), missing=len(result.missing_evidence),
                                           completeness_pct=result.completeness_pct)
        r.validation_status = "COMPLETE" if result.is_complete else "INCOMPLETE"
        db.set_status(s, r, "VALIDATION_PENDING")
    return {"validation": result}


def mark_rework(state: WorkflowState) -> dict[str, Any]:
    rid, v = state["request_id"], state["validation"]
    with session_scope() as s:
        r = db.get_request(s, rid)
        db.set_status(s, r, "REWORK_REQUIRED")
        missing = ", ".join(evidence_label(e) for e in v.missing_evidence)
        db.add_event(s, rid, "Validation", "warning", "Completeness check: evidence missing",
                     f"{len(v.missing_evidence)} of {len(v.required_evidence)} required items missing ({missing}). "
                     "Awaiting Human Validator action.", actor_name="Completeness check", actor_role="System")
        from app.orchestrator.service import notify_validators
        notify_validators(s, rid, [evidence_label(e) for e in v.missing_evidence])
    return {}


def mark_pending(state: WorkflowState) -> dict[str, Any]:
    rid, v = state["request_id"], state["validation"]
    with session_scope() as s:
        db.add_event(s, rid, "Validation", "info", "Awaiting validator confirmation",
                     f"Completeness {v.completeness_pct}% after retry.", actor_name="Completeness check", actor_role="System")
    return {}


def review_package_node(state: WorkflowState) -> dict[str, Any]:
    from app.orchestrator.service import prepare_review_package
    with session_scope() as s:
        prepare_review_package(s, state["request_id"], validated_by="Automated completeness check", note=None, actor=None)
    return {}


def route_after_classify(state: WorkflowState) -> str:
    return "stop" if state.get("halted") else "continue"


def route_after_validate(state: WorkflowState) -> str:
    if state.get("mode") == "retry":
        return "pending"
    return "complete" if state["validation"].is_complete else "rework"


def route_entry(state: WorkflowState) -> str:
    return state.get("mode", "full")


def build_graph():
    g = StateGraph(WorkflowState)
    g.add_node("understand", understand)
    g.add_node("classify", classify_node)
    g.add_node("load_context", load_context)
    g.add_node("resolve_requirements", resolve_requirements_node)
    g.add_node("resolve_sources", resolve_sources_node)
    g.add_node("plan", plan_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("process", observe_node("evidence_processing")(process_node))
    g.add_node("validate", observe_node("completeness_validation")(validate_node))
    g.add_node("rework", mark_rework)
    g.add_node("validation_pending", mark_pending)
    g.add_node("review_package", observe_node("final_packaging")(review_package_node))

    g.add_conditional_edges(START, route_entry, {"full": "understand", "retry": "load_context"})
    g.add_edge("understand", "classify")
    g.add_conditional_edges("classify", route_after_classify, {"continue": "resolve_requirements", "stop": END})
    g.add_edge("load_context", "resolve_requirements")
    g.add_edge("resolve_requirements", "resolve_sources")
    g.add_edge("resolve_sources", "plan")
    g.add_edge("plan", "retrieve")
    g.add_edge("retrieve", "process")
    g.add_edge("process", "validate")
    g.add_conditional_edges("validate", route_after_validate,
                            {"complete": "review_package", "rework": "rework", "pending": "validation_pending"})
    g.add_edge("review_package", END)
    g.add_edge("rework", END)
    g.add_edge("validation_pending", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run(request_id: str, mode: str = "full", target_evidence: list[str] | None = None) -> WorkflowState:
    """Execute the workflow; failures move the request to REWORK_REQUIRED with a user-actionable event."""
    obs = get_observability()
    try:
        with obs.workflow("audit_evidence_workflow", request_id=request_id, operation=mode, component="orchestrator",
                          metadata={"mode": mode, "target_evidence": target_evidence}) as wf:
            state = get_graph().invoke({"request_id": request_id, "mode": mode, "target_evidence": target_evidence},
                                       config=graph_config(obs, run_name="orchestrator", tags=[f"mode:{mode}"]))
            v = state.get("validation")
            wf.annotate(halted=bool(state.get("halted")), query_type=state.get("query_type"),
                        validation_complete=v.is_complete if v is not None else None)
            return state
    except Exception:
        log.exception("workflow failed", extra={"request_id": request_id})
        with session_scope() as s:
            r = db.get_request(s, request_id)
            if r.status in ("REQUEST_CREATED", "PROCESSING", "VALIDATION_PENDING"):
                r.status = "REWORK_REQUIRED"
            db.add_event(s, request_id, "Processing", "error", "Processing interrupted",
                         "Evidence retrieval could not complete. A validator can retry the request.", **SYSTEM)
            if r.status == "REWORK_REQUIRED":
                from app.orchestrator.service import notify_validators
                notify_validators(s, request_id, ["Evidence retrieval was interrupted — retry required"])
        return {"request_id": request_id, "halted": True}

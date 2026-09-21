"""LangGraph orchestrator wiring.

    initialize -> understand -> [unsupported? finalize]
               -> load_requirements -> check_required_inputs
                    -> [mandatory input missing? finalize, asking the auditor]
               -> create_task -> retrieve -> validate
               -> decide:
                    COMPLETE / NEEDS_REVIEW      -> generate_package
                    INCOMPLETE, retries left     -> increment_retry -> retrieve
                    INCOMPLETE, retries spent    -> generate_package
               -> await_review -> finalize

The retry edge is bounded by MAX_RETRIES, so the loop cannot spin forever.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph.nodes import make_nodes
from app.graph.state import AuditWorkflowState
from app.services import repository
from app.services.validation import (
    STATUS_COMPLETE,
    STATUS_ERROR,
    STATUS_INCOMPLETE,
)


def _after_understanding(state: AuditWorkflowState) -> str:
    """Stop early when the request is unsupported or failed to parse."""
    if state.get("workflow_status") in (
        repository.STATUS_UNSUPPORTED,
        repository.STATUS_ERROR,
    ):
        return "finalize"
    return "load_requirements"


def _after_input_check(state: AuditWorkflowState) -> str:
    """Halt before retrieval when mandatory inputs are missing.

    Searching on a partial key set would return confidently wrong evidence,
    so the run stops and waits for the auditor to supply the values.
    """
    if state.get("missing_parameters"):
        return "finalize"
    return "create_retrieval_task"


def decide_retry(state: AuditWorkflowState) -> str:
    """Route on the validation outcome within the retry budget."""
    result = state.get("validation_result") or {}
    status = result.get("validation_status")
    retry_count = state.get("retry_count", 0)
    max_retries = get_settings().max_retries

    if status == STATUS_ERROR:
        return "generate_package"
    if status == STATUS_COMPLETE:
        return "generate_package"

    # Only a genuinely searchable gap justifies another pass. Items awaiting
    # human judgement are not retryable, so NEEDS_REVIEW goes straight on.
    if status == STATUS_INCOMPLETE and retry_count < max_retries:
        return "increment_retry"

    return "generate_package"


def build_workflow(progress=None):
    """Compile the graph. `progress` receives node-level events."""
    nodes = make_nodes(progress)
    graph = StateGraph(AuditWorkflowState)

    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "initialize_request")
    graph.add_edge("initialize_request", "understand_query")
    graph.add_conditional_edges(
        "understand_query",
        _after_understanding,
        {"load_requirements": "load_requirements", "finalize": "finalize"},
    )
    graph.add_edge("load_requirements", "check_required_inputs")
    graph.add_conditional_edges(
        "check_required_inputs",
        _after_input_check,
        {"create_retrieval_task": "create_retrieval_task", "finalize": "finalize"},
    )
    graph.add_edge("create_retrieval_task", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "validate_evidence")
    graph.add_conditional_edges(
        "validate_evidence",
        decide_retry,
        {
            "increment_retry": "increment_retry",
            "generate_package": "generate_package",
        },
    )
    # The retry edge: back to retrieval with only the outstanding items.
    graph.add_edge("increment_retry", "retrieve_evidence")
    graph.add_edge("generate_package", "await_review")
    graph.add_edge("await_review", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()

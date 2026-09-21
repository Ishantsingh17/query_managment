"""Workflow state carried through the LangGraph orchestrator."""

from __future__ import annotations

from typing import Any, TypedDict


class AuditWorkflowState(TypedDict, total=False):
    # Identity and input
    request_id: str
    raw_query: str

    # Query understanding
    parsed_query: dict[str, Any]
    use_case_id: str
    requirement_name: str
    confidence: float
    parse_source: str
    ambiguities: list[str]

    # Planning
    search_parameters: dict[str, Any]
    search_context: dict[str, Any]
    required_evidence: list[str]
    retrieval_task: dict[str, Any]

    # Mandatory inputs the request did not supply. While this is non-empty the
    # workflow refuses to search, and the auditor is asked to fill the gaps.
    missing_parameters: list[str]
    clarification_question: str | None
    # raw_query plus every clarification answer, which is what gets parsed.
    # raw_query itself is never rewritten, so the audit trail stays honest.
    effective_query: str | None
    # Explicit key/value answers, applied on top of whatever parsing found.
    clarified_parameters: dict[str, Any]
    # Each answer the auditor gave, kept separately so the original query is
    # never rewritten and the audit trail stays honest.
    clarifications: list[dict[str, Any]]

    # Retrieval
    found_evidence: dict[str, dict[str, Any]]
    missing_evidence: list[str]
    database_results: list[dict[str, Any]]
    identifier_origin: dict[str, str]
    unlocked_by: dict[str, str]

    # Validation and retry
    validation_result: dict[str, Any]
    retry_count: int
    retry_note: str | None

    # Output
    package_path: str | None
    package_summary: dict[str, Any]

    # Bookkeeping
    workflow_status: str
    error_code: str | None
    errors: list[str]


def initial_state(request_id: str, raw_query: str) -> AuditWorkflowState:
    return AuditWorkflowState(
        request_id=request_id,
        raw_query=raw_query,
        parsed_query={},
        use_case_id="",
        requirement_name="",
        confidence=0.0,
        parse_source="",
        ambiguities=[],
        search_parameters={},
        search_context={},
        required_evidence=[],
        retrieval_task={},
        missing_parameters=[],
        clarification_question=None,
        effective_query=None,
        clarified_parameters={},
        clarifications=[],
        found_evidence={},
        missing_evidence=[],
        database_results=[],
        identifier_origin={},
        unlocked_by={},
        validation_result={},
        retry_count=0,
        retry_note=None,
        package_path=None,
        package_summary={},
        workflow_status="RECEIVED",
        error_code=None,
        errors=[],
    )

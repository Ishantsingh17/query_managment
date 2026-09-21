"""The workflow nodes.

Each node advances the state and persists what it learned, so the API can
report accurate progress while a run is still in flight.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents import query_understanding
from app.agents.retrieval_agent import retrieve_evidence
from app.catalog.loader import enabled_databases, get_use_case, required_evidence_for
from app.config import get_settings
from app.graph.state import AuditWorkflowState
from app.schemas import SearchParameters
from app.services import packaging, repository, required_inputs, staging, validation

logger = logging.getLogger(__name__)

STEP_INITIALIZE = "initialize_request"
STEP_UNDERSTAND = "understand_query"
STEP_REQUIREMENTS = "load_requirements"
STEP_CHECK_INPUTS = "check_required_inputs"
STEP_TASK = "create_retrieval_task"
STEP_RETRIEVE = "retrieve_evidence"
STEP_VALIDATE = "validate_evidence"
STEP_PACKAGE = "generate_package"
STEP_AWAIT_REVIEW = "await_review"
STEP_FINALIZE = "finalize"


async def _pace() -> None:
    delay_ms = get_settings().demo_step_delay_ms
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)


def _persist(state: AuditWorkflowState, step: str) -> None:
    """Snapshot the state so pollers see progress mid-run."""
    repository.save_workflow_state(state["request_id"], step, dict(state))


def make_nodes(progress=None):
    """Build the node functions, closing over an optional progress hook."""

    async def emit(event: dict[str, Any]) -> None:
        if progress:
            await progress(event)

    # --- 1. initialize ---------------------------------------------------
    async def initialize_request(state: AuditWorkflowState) -> dict[str, Any]:
        request_id = state["request_id"]
        staging.ensure_staging(request_id)
        repository.update_request(request_id, status=repository.STATUS_UNDERSTANDING)
        update = {"workflow_status": repository.STATUS_UNDERSTANDING}
        _persist({**state, **update}, STEP_INITIALIZE)
        await emit({"event": "request_initialized", "request_id": request_id})
        return update

    # --- 2. understand ---------------------------------------------------
    async def understand_query(state: AuditWorkflowState) -> dict[str, Any]:
        request_id = state["request_id"]
        await _pace()

        try:
            # Parse the original request plus any clarification answers.
            # raw_query stays untouched for traceability.
            text = state.get("effective_query") or state["raw_query"]
            envelope = await asyncio.to_thread(query_understanding.understand, text)
        except Exception as exc:
            logger.exception("Query understanding failed outright")
            repository.update_request(request_id, status=repository.STATUS_ERROR)
            update = {
                "workflow_status": repository.STATUS_ERROR,
                "error_code": "QUERY_PARSE_FAILED",
                "errors": [*state.get("errors", []), f"Query understanding failed: {exc}"],
            }
            _persist({**state, **update}, STEP_UNDERSTAND)
            return update

        parsed = envelope.parsed
        payload = {
            **parsed.model_dump(),
            "parse_source": envelope.parse_source,
            "model": envelope.model,
            "fallback_reason": envelope.fallback_reason,
        }
        repository.save_parsed_query(request_id, payload, parsed.confidence)

        if not parsed.is_supported:
            repository.update_request(request_id, status=repository.STATUS_UNSUPPORTED)
            update = {
                "parsed_query": payload,
                "use_case_id": "UNSUPPORTED",
                "confidence": parsed.confidence,
                "parse_source": envelope.parse_source,
                "ambiguities": parsed.ambiguities,
                "workflow_status": repository.STATUS_UNSUPPORTED,
                "error_code": "UNSUPPORTED_QUERY",
            }
            _persist({**state, **update}, STEP_UNDERSTAND)
            await emit({"event": "query_unsupported", "request_id": request_id})
            return update

        spec = get_use_case(parsed.use_case_id)
        repository.update_request(
            request_id,
            status=repository.STATUS_PLANNING,
            use_case_id=parsed.use_case_id,
            requirement_name=spec.name if spec else parsed.requirement,
        )

        # A resumed run (a reviewer-triggered retry) re-parses the query, so
        # re-apply identifiers discovered by earlier passes. Without this the
        # retry would search with only the original request's parameters and
        # lose keys such as a ses_number learned from another source.
        context = parsed.search_parameters.to_search_context()
        discovered = state.get("identifier_origin", {})
        previous = state.get("search_context", {})
        for key in discovered:
            if key in previous:
                context.setdefault(key, previous[key])

        # Values the auditor supplied through a clarification win over parsing,
        # so a resumed run never loses what they already answered.
        clarified = state.get("clarified_parameters") or {}
        supplied = {**parsed.search_parameters.provided(), **clarified}
        if clarified:
            context = {**SearchParameters(**supplied).to_search_context(), **context}

        update = {
            "parsed_query": payload,
            "use_case_id": parsed.use_case_id,
            "requirement_name": spec.name if spec else parsed.requirement,
            "confidence": parsed.confidence,
            "parse_source": envelope.parse_source,
            "ambiguities": parsed.ambiguities,
            "search_parameters": supplied,
            "search_context": context,
            "workflow_status": repository.STATUS_PLANNING,
        }
        _persist({**state, **update}, STEP_UNDERSTAND)
        await emit(
            {
                "event": "query_understood",
                "use_case_id": parsed.use_case_id,
                "confidence": parsed.confidence,
            }
        )
        return update

    # --- 3. requirements -------------------------------------------------
    async def load_requirements(state: AuditWorkflowState) -> dict[str, Any]:
        await _pace()
        # Deterministic catalog lookup - the LLM has no say here.
        required = required_evidence_for(state["use_case_id"])
        update = {"required_evidence": required}
        _persist({**state, **update}, STEP_REQUIREMENTS)
        await emit({"event": "requirements_loaded", "required_evidence": required})
        return update

    # --- 3b. mandatory input gate ---------------------------------------
    async def check_required_inputs(state: AuditWorkflowState) -> dict[str, Any]:
        """Refuse to search until the use case's mandatory inputs are present.

        Searching a source system on a partial key set does not fail loudly -
        it returns the wrong evidence with full confidence. So the run stops
        here and asks the auditor instead.
        """
        request_id = state["request_id"]
        spec = get_use_case(state.get("use_case_id", ""))
        missing = required_inputs.missing_required(spec, state.get("search_parameters", {}))

        if not missing:
            update = {"missing_parameters": [], "clarification_question": None}
            _persist({**state, **update}, STEP_CHECK_INPUTS)
            return update

        question = required_inputs.question_for(spec, missing)
        repository.update_request(request_id, status=repository.STATUS_NEEDS_INPUT)
        update = {
            "missing_parameters": missing,
            "clarification_question": question,
            "workflow_status": repository.STATUS_NEEDS_INPUT,
            "error_code": "MISSING_REQUIRED_INPUT",
        }
        _persist({**state, **update}, STEP_CHECK_INPUTS)
        await emit(
            {
                "event": "input_required",
                "request_id": request_id,
                "missing_parameters": missing,
            }
        )
        return update

    # --- 4. retrieval task ----------------------------------------------
    async def create_retrieval_task(state: AuditWorkflowState) -> dict[str, Any]:
        task = {
            "request_id": state["request_id"],
            "use_case_id": state["use_case_id"],
            "search_parameters": state.get("search_context", {}),
            "required_evidence": state.get("required_evidence", []),
            "found_evidence": list(state.get("found_evidence", {})),
            "missing_evidence": state.get("missing_evidence", [])
            or list(state.get("required_evidence", [])),
            "retry_count": state.get("retry_count", 0),
        }
        repository.update_request(state["request_id"], status=repository.STATUS_RETRIEVING)
        update = {"retrieval_task": task, "workflow_status": repository.STATUS_RETRIEVING}
        _persist({**state, **update}, STEP_TASK)
        await emit({"event": "retrieval_task_created", "task": task})
        return update

    # --- 5. retrieve -----------------------------------------------------
    async def retrieve_evidence_node(state: AuditWorkflowState) -> dict[str, Any]:
        retry_count = state.get("retry_count", 0)
        pass_number = retry_count + 1

        # On a retry only the outstanding items are re-searched.
        wanted = state.get("missing_evidence") or state.get("required_evidence", [])

        outcome = await retrieve_evidence(
            request_id=state["request_id"],
            use_case_id=state["use_case_id"],
            required_evidence=list(wanted),
            search_context=dict(state.get("search_context", {})),
            already_found=dict(state.get("found_evidence", {})),
            identifier_origin=dict(state.get("identifier_origin", {})),
            # The auditor's stated scope, rebuilt from the parsed parameters
            # so mid-run identifier enrichment cannot narrow an aggregate.
            scope_context=SearchParameters(
                **(state.get("search_parameters") or {})
            ).to_search_context(),
            # Narrows compiled evidence only. The auditor asked for one report
            # type, so the transaction listing should hold that type's lines -
            # while the document checklist still requires all three reports.
            tabular_filters={
                "report_type": (state.get("search_parameters") or {}).get("report_type")
            },
            pass_number=pass_number,
            progress=progress,
        )

        # Missing is recomputed against the full checklist, not just this pass.
        required = state.get("required_evidence", [])
        missing = [code for code in required if code not in outcome.found]

        update = {
            "found_evidence": outcome.found,
            "missing_evidence": missing,
            "database_results": [*state.get("database_results", []), *outcome.attempts],
            "search_context": outcome.context,
            "identifier_origin": outcome.identifier_origin,
            "unlocked_by": {**state.get("unlocked_by", {}), **outcome.unlocked_by},
            "errors": [*state.get("errors", []), *outcome.errors],
        }
        _persist({**state, **update}, STEP_RETRIEVE)
        await emit({"event": "retrieval_pass_complete", "pass_number": pass_number, "missing": missing})
        return update

    # --- 6. validate -----------------------------------------------------
    async def validate_evidence(state: AuditWorkflowState) -> dict[str, Any]:
        request_id = state["request_id"]
        repository.update_request(request_id, status=repository.STATUS_VALIDATING)
        await _pace()

        parameters = SearchParameters(**(state.get("search_parameters") or {}))
        retrieved = repository.list_retrieved_evidence(request_id)
        retries_exhausted = state.get("retry_count", 0) >= get_settings().max_retries

        result = validation.validate(
            use_case_id=state["use_case_id"],
            parameters=parameters,
            required_evidence=state.get("required_evidence", []),
            found_evidence=state.get("found_evidence", {}),
            retrieved_evidence=retrieved,
            retries_exhausted=retries_exhausted,
            errors=state.get("errors") or None,
        )

        repository.save_validation_result(
            request_id,
            result["validation_status"],
            result["checks"],
            result["missing_evidence"],
        )
        staging.write_validation_snapshot(request_id, result)

        update = {"validation_result": result, "workflow_status": repository.STATUS_VALIDATING}
        _persist({**state, **update}, STEP_VALIDATE)
        await emit({"event": "validation_complete", "status": result["validation_status"]})
        return update

    # --- 7. retry bookkeeping -------------------------------------------
    async def increment_retry(state: AuditWorkflowState) -> dict[str, Any]:
        retry_count = state.get("retry_count", 0) + 1
        repository.update_request(state["request_id"], status=repository.STATUS_RETRIEVING)
        update = {"retry_count": retry_count, "workflow_status": repository.STATUS_RETRIEVING}
        _persist({**state, **update}, STEP_RETRIEVE)
        await emit({"event": "retry_started", "retry_count": retry_count})
        return update

    # --- 8. package ------------------------------------------------------
    async def generate_package(state: AuditWorkflowState) -> dict[str, Any]:
        await _pace()
        note = _retry_note(state)
        summary = packaging.generate_package(state["request_id"], {**state, "retry_note": note})
        update = {
            "package_path": summary.get("package_path"),
            "package_summary": summary,
            "retry_note": note,
        }
        _persist({**state, **update}, STEP_PACKAGE)
        await emit({"event": "package_generated", "package_path": summary.get("package_path")})
        return update

    # --- 9. await review -------------------------------------------------
    async def await_review(state: AuditWorkflowState) -> dict[str, Any]:
        repository.update_request(state["request_id"], status=repository.STATUS_READY_FOR_REVIEW)
        update = {"workflow_status": repository.STATUS_READY_FOR_REVIEW}
        _persist({**state, **update}, STEP_AWAIT_REVIEW)
        await emit({"event": "ready_for_review", "request_id": state["request_id"]})
        return update

    # --- 10. finalize ----------------------------------------------------
    async def finalize(state: AuditWorkflowState) -> dict[str, Any]:
        status = state.get("workflow_status", repository.STATUS_READY_FOR_REVIEW)
        update = {"workflow_status": status}
        _persist({**state, **update}, STEP_FINALIZE)
        await emit({"event": "workflow_finished", "status": status})
        return update

    return {
        "initialize_request": initialize_request,
        "understand_query": understand_query,
        "load_requirements": load_requirements,
        "check_required_inputs": check_required_inputs,
        "create_retrieval_task": create_retrieval_task,
        "retrieve_evidence": retrieve_evidence_node,
        "validate_evidence": validate_evidence,
        "increment_retry": increment_retry,
        "generate_package": generate_package,
        "await_review": await_review,
        "finalize": finalize,
    }


def _retry_note(state: AuditWorkflowState) -> str | None:
    """Explain what a retry achieved, naming the source that unlocked it.

    Derived from recorded state rather than hard-coded, so the sentence stays
    true if the data or the search order changes.
    """
    retry_count = state.get("retry_count", 0)
    if not retry_count:
        return None

    found = state.get("found_evidence", {})
    spec = get_use_case(state.get("use_case_id", ""))
    late = [
        (code, detail)
        for code, detail in found.items()
        if detail.get("pass_number", 1) > 1
    ]
    plural = "retries" if retry_count > 1 else "retry"

    if not late:
        return f"{retry_count} {plural} performed - no additional evidence was recovered."

    # Name the sources the way the rest of the UI does.
    names = {db.database_id: db.name for db in enabled_databases()}

    parts: list[str] = []
    for code, detail in late:
        label = spec.label_for(code) if spec else code
        origin = state.get("unlocked_by", {}).get(code)
        source = detail.get("source_database_id")
        source_name = names.get(source, source)
        if origin:
            parts.append(
                f"{label} was found in {source_name} on a later attempt via related "
                f"identifiers from {names.get(origin, origin)}"
            )
        else:
            parts.append(f"{label} was found in {source_name} on a later attempt")
    return f"{retry_count} {plural} performed - " + "; ".join(parts) + "."

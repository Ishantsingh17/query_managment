"""Workflow execution.

Runs the LangGraph orchestrator as a background task. Every stage persists
its state as it completes, so the UI can poll and watch the sequential search
advance rather than waiting for a single blocking call.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.catalog.loader import get_use_case
from app.graph.state import initial_state
from app.graph.workflow import build_workflow
from app.services import repository, required_inputs
from app.services.db import utc_now

logger = logging.getLogger(__name__)

# Requests currently executing, so a duplicate /run is a no-op rather than a
# second concurrent traversal of the same request.
_running: set[str] = set()
_lock = asyncio.Lock()


async def _log_progress(event: dict[str, Any]) -> None:
    logger.info("workflow event: %s", event.get("event"), extra={"detail": event})


async def run_workflow(request_id: str, *, resume_state: dict[str, Any] | None = None) -> None:
    """Execute the workflow for one request to completion."""
    async with _lock:
        if request_id in _running:
            logger.info("Request %s is already running; ignoring duplicate start", request_id)
            return
        _running.add(request_id)

    try:
        request = repository.get_request(request_id)
        if request is None:
            logger.warning("Cannot run unknown request %s", request_id)
            return

        state = resume_state or initial_state(request_id, request["raw_query"])
        workflow = build_workflow(progress=_log_progress)

        try:
            await workflow.ainvoke(state)
        except Exception as exc:
            logger.exception("Workflow failed for %s", request_id)
            repository.update_request(request_id, status=repository.STATUS_ERROR)
            snapshot = repository.get_workflow_state(request_id) or {}
            current = snapshot.get("state", {}) if isinstance(snapshot, dict) else {}
            repository.save_workflow_state(
                request_id,
                "error",
                {
                    **current,
                    "workflow_status": repository.STATUS_ERROR,
                    "error_code": "ERROR",
                    "errors": [*(current.get("errors") or []), str(exc)],
                },
            )
    finally:
        async with _lock:
            _running.discard(request_id)


async def retry_workflow(request_id: str) -> None:
    """Re-run retrieval for whatever is still missing.

    Resumes from the persisted state so already-staged evidence is preserved
    and only the outstanding items are searched again.
    """
    snapshot = repository.get_workflow_state(request_id)
    request = repository.get_request(request_id)
    if request is None:
        logger.warning("Cannot retry unknown request %s", request_id)
        return

    if not snapshot or not snapshot.get("state"):
        # Nothing to resume from - start a fresh run.
        await run_workflow(request_id)
        return

    state = dict(snapshot["state"])
    # A reviewer-triggered retry gets its own budget so an explicit request is
    # never silently dropped for having exhausted the automatic allowance.
    state["retry_count"] = 0
    state["validation_result"] = {}
    state.setdefault("raw_query", request["raw_query"])
    state.setdefault("request_id", request_id)

    required = state.get("required_evidence") or []
    found = state.get("found_evidence") or {}
    state["missing_evidence"] = [code for code in required if code not in found]

    if not state["missing_evidence"]:
        logger.info("Retry requested for %s but nothing is missing", request_id)

    await run_workflow(request_id, resume_state=state)


def clarification_state(request_id: str) -> dict[str, Any] | None:
    """The persisted state for a request awaiting clarification."""
    snapshot = repository.get_workflow_state(request_id)
    if not snapshot or not snapshot.get("state"):
        return None
    return dict(snapshot["state"])


async def clarify_workflow(
    request_id: str,
    *,
    answer: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept the auditor's answer and resume, or ask again.

    A free-text answer is appended to the request and the whole thing is
    re-parsed, so "SOB 101, NAC 5000-5999, AP" fills the gaps the original
    sentence left. Structured key/value answers are applied on top. The
    original raw_query is never rewritten.

    Returns {"resumed": bool, "missing": [...]}.
    """
    request = repository.get_request(request_id)
    if request is None:
        return {"resumed": False, "missing": [], "error": "unknown request"}

    state = clarification_state(request_id) or initial_state(request_id, request["raw_query"])

    # 1. Fold the answer in.
    if answer and answer.strip():
        base = state.get("effective_query") or request["raw_query"]
        state["effective_query"] = f"{base} {answer.strip()}"
    if parameters:
        clean = {k: v for k, v in parameters.items() if v not in (None, "", [])}
        state["clarified_parameters"] = {**(state.get("clarified_parameters") or {}), **clean}

    state["clarifications"] = [
        *(state.get("clarifications") or []),
        {"answer": answer, "parameters": parameters or {}, "at": utc_now()},
    ]

    # 2. Re-parse so the answer actually becomes search parameters.
    from app.agents import query_understanding

    text = state.get("effective_query") or request["raw_query"]
    envelope = await asyncio.to_thread(query_understanding.understand, text)
    parsed = envelope.parsed

    supplied = {
        **parsed.search_parameters.provided(),
        **(state.get("clarified_parameters") or {}),
    }
    use_case_id = (
        parsed.use_case_id
        if parsed.is_supported
        else state.get("use_case_id", "")
    )
    spec = get_use_case(use_case_id)
    missing = required_inputs.missing_required(spec, supplied)

    state["use_case_id"] = use_case_id
    state["search_parameters"] = supplied
    state["missing_parameters"] = missing
    state["clarification_question"] = required_inputs.question_for(spec, missing)

    # 3. Still short? Ask again rather than searching on a partial key set.
    if missing:
        state["workflow_status"] = repository.STATUS_NEEDS_INPUT
        repository.update_request(request_id, status=repository.STATUS_NEEDS_INPUT)
        repository.save_workflow_state(request_id, "check_required_inputs", state)
        return {"resumed": False, "missing": missing}

    # 4. Complete now. Clear the halt and hand back so the caller can start
    #    the run in the background - the auditor gets an immediate answer on
    #    whether their input was enough, and still sees the timeline animate.
    state["error_code"] = None
    state["workflow_status"] = repository.STATUS_PLANNING
    repository.update_request(request_id, status=repository.STATUS_PLANNING)
    repository.save_workflow_state(request_id, "check_required_inputs", state)
    return {"resumed": True, "missing": []}


async def resume_workflow(request_id: str) -> None:
    """Continue a request whose missing inputs have just been supplied."""
    state = clarification_state(request_id)
    if state is None:
        await run_workflow(request_id)
        return
    await run_workflow(request_id, resume_state=state)


def is_running(request_id: str) -> bool:
    return request_id in _running

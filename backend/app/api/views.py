"""Composite view builders.

The frontend renders these payloads directly, so all derivation - checklist
statuses, the progress timeline, per-database match counts - happens here.
The UI stays a renderer and holds no workflow logic, and the number of
timeline steps follows the database registry rather than anything hard-coded.
"""

from __future__ import annotations

from typing import Any

from app.catalog.loader import enabled_databases, get_use_case, load_use_cases
from app.schemas import (
    AuditRequestDetail,
    AuditRequestSummary,
    DatabaseAttemptView,
    EvidenceChecklistItem,
    EvidenceRow,
    MissingParameter,
    PackageFile,
    PackageView,
    ParameterView,
    TimelineStep,
    TrailEntry,
    UseCaseView,
    ValidationCheckView,
    ValidationView,
)
from app.services import repository, required_inputs, staging
from app.services.ordering import order_by_checklist

# Checklist / row statuses
PENDING = "PENDING"
SEARCHING = "SEARCHING"
FOUND = "FOUND"
MISSING = "MISSING"
VALIDATED = "VALIDATED"

# Timeline statuses
STEP_PENDING = "PENDING"
STEP_ACTIVE = "ACTIVE"
STEP_COMPLETE = "COMPLETE"
STEP_ERROR = "ERROR"


def _plural_matches(count: int) -> str:
    return f"{count} match" if count == 1 else f"{count} matches"


# Aggregate evidence is compiled from several systems, so it has no single
# source database. It is recorded against this synthetic id.
GENERATED_SOURCE_ID = "GENERATED"
GENERATED_SOURCE_NAME = "Compiled extract"


def _database_names() -> dict[str, str]:
    """Map database id -> the source system name from the registry."""
    names = {spec.database_id: spec.name for spec in enabled_databases()}
    names[GENERATED_SOURCE_ID] = GENERATED_SOURCE_NAME
    return names


def use_case_views() -> list[UseCaseView]:
    views = []
    for use_case_id, spec in load_use_cases().items():
        views.append(
            UseCaseView(
                use_case_id=use_case_id,
                name=spec.name,
                short_name=spec.short_name,
                description=spec.description,
                icon=spec.icon,
                required_parameters=list(spec.required_parameters),
                required_parameter_labels=[
                    spec.parameter_label(key) for key in spec.all_parameters
                ],
                required_evidence=[
                    EvidenceChecklistItem(
                        code=item.code,
                        label=item.label,
                        status=PENDING,
                        human_required=item.human_required,
                    )
                    for item in spec.evidence
                ],
            )
        )
    return views


def request_summary(request: dict[str, Any]) -> AuditRequestSummary:
    request_id = request["id"]
    spec = get_use_case(request.get("use_case_id") or "")
    evidence = repository.list_retrieved_evidence(request_id)
    validation = repository.latest_validation(request_id)

    return AuditRequestSummary(
        request_id=request_id,
        raw_query=request["raw_query"],
        status=request["status"],
        use_case_id=request.get("use_case_id"),
        requirement_name=request.get("requirement_name"),
        created_at=request["created_at"],
        updated_at=request["updated_at"],
        evidence_found=len(evidence),
        evidence_required=len(spec.evidence_codes) if spec else 0,
        validation_status=validation.get("validation_status") if validation else None,
    )


def _parameter_views(spec, parameters: dict[str, Any]) -> list[ParameterView]:
    views: list[ParameterView] = []
    # Mandatory inputs first, in catalog order, then anything extra.
    ordered = list(spec.all_parameters) if spec else []
    ordered += [key for key in parameters if key not in ordered]

    for key in ordered:
        value = parameters.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        label = spec.parameter_label(key) if spec else key.replace("_", " ").title()
        views.append(ParameterView(key=key, label=label, value=str(value)))
    return views


def _checklist(
    spec,
    required: list[str],
    evidence_by_type: dict[str, dict[str, Any]],
    validation_status: str | None,
    active_search: set[str],
    retrieval_started: bool,
) -> list[EvidenceChecklistItem]:
    names = _database_names()
    items: list[EvidenceChecklistItem] = []
    for code in required:
        requirement = spec.requirement(code) if spec else None
        label = spec.label_for(code) if spec else code
        found = evidence_by_type.get(code)

        if found:
            status = VALIDATED if validation_status == "COMPLETE" else FOUND
        elif code in active_search:
            status = SEARCHING
        elif retrieval_started:
            status = MISSING
        else:
            status = PENDING

        items.append(
            EvidenceChecklistItem(
                code=code,
                label=label,
                status=status,
                identifier=found.get("identifier") if found else None,
                source_database_id=found.get("source_database_id") if found else None,
                source_database_name=(
                    names.get(found["source_database_id"], found["source_database_id"])
                    if found
                    else None
                ),
                evidence_id=found.get("id") if found else None,
                human_required=bool(requirement.human_required) if requirement else False,
                generated=bool(requirement.generated) if requirement else False,
                row_count=(found.get("metadata") or {}).get("row_count") if found else None,
            )
        )
    return items


def _timeline(
    request: dict[str, Any],
    state: dict[str, Any],
    attempts: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    validation: dict[str, Any] | None,
    package: dict[str, Any] | None,
    spec,
) -> list[TimelineStep]:
    status = request["status"]
    steps: list[TimelineStep] = []

    # 1. Request received
    steps.append(
        TimelineStep(
            key="request_received",
            label="Request Received",
            status=STEP_COMPLETE,
            detail=None,
        )
    )

    # 2. Query understood
    parsed = repository.get_parsed_query(request["id"])
    if status == repository.STATUS_UNSUPPORTED:
        understood = STEP_ERROR
        detail = "Unsupported request"
    elif parsed:
        understood = STEP_COMPLETE
        confidence = parsed.get("confidence")
        detail = f"{round(confidence * 100)}% confidence" if confidence else None
    elif status == repository.STATUS_UNDERSTANDING:
        understood, detail = STEP_ACTIVE, None
    else:
        understood, detail = STEP_PENDING, None
    steps.append(
        TimelineStep(
            key="query_understood", label="Query Understood", status=understood, detail=detail
        )
    )

    # 3. Requirements identified
    required = state.get("required_evidence") or []
    if state.get("missing_parameters"):
        # Halted for missing mandatory inputs: nothing was searched.
        req_status = STEP_ERROR
        req_detail = "Input required"
    elif required:
        req_status = STEP_COMPLETE
        req_detail = f"{len(required)} items"
    elif status == repository.STATUS_PLANNING:
        req_status, req_detail = STEP_ACTIVE, None
    else:
        req_status, req_detail = STEP_PENDING, None
    steps.append(
        TimelineStep(
            key="requirements_identified",
            label="Requirements Identified",
            status=req_status,
            detail=req_detail,
        )
    )

    # 4..N. One step per configured database.
    #
    # Counts are cumulative across passes and derived from what was actually
    # sourced from each database, which is why the retry's SES shows against
    # DB-03 rather than against the pass that found it.
    generated_codes = set(spec.generated_codes) if spec else set()

    attempts_by_db: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        # Row fetches for a compiled extract are not document searches; their
        # result counts are row counts and would distort "N matches".
        requested = attempt.get("requested_evidence") or []
        if requested and set(requested) <= generated_codes:
            continue
        attempts_by_db.setdefault(attempt["database_id"], []).append(attempt)

    evidence_by_db: dict[str, list[str]] = {}
    for item in evidence:
        if item["source_database_id"] == GENERATED_SOURCE_ID:
            continue
        label = spec.label_for(item["document_type"]) if spec else item["document_type"]
        evidence_by_db.setdefault(item["source_database_id"], []).append(label)

    for database in enabled_databases():
        db_attempts = attempts_by_db.get(database.database_id, [])
        sourced = evidence_by_db.get(database.database_id, [])

        if not db_attempts:
            # Never searched. If the run has already settled and earlier
            # sources were searched, the checklist filled before reaching this
            # one - say so, rather than leaving a grey node that reads as
            # "still waiting".
            step_status, detail, sub_detail = STEP_PENDING, None, None
            settled = request["status"] not in repository.ACTIVE_STATUSES
            if settled and attempts_by_db:
                detail = "Not needed"
                sub_detail = "Checklist already complete"
        elif any(a["status"] == "SEARCHING" for a in db_attempts):
            step_status, detail, sub_detail = STEP_ACTIVE, "Searching", None
        elif all(a["status"] not in ("COMPLETED", "SEARCHING") for a in db_attempts):
            step_status = STEP_ERROR
            detail = "Unavailable"
            sub_detail = next((a.get("error_message") for a in db_attempts if a.get("error_message")), None)
        else:
            step_status = STEP_COMPLETE
            detail = _plural_matches(len(sourced))
            sub_detail = ", ".join(sourced) if sourced else None

        steps.append(
            TimelineStep(
                # The key stays the stable database id; the label is the
                # source system name an auditor recognises.
                key=f"database_{database.database_id}",
                label=database.name,
                status=step_status,
                detail=detail,
                sub_detail=sub_detail,
            )
        )

    # N+1. Validating
    if validation:
        val_status = STEP_COMPLETE if validation["validation_status"] == "COMPLETE" else STEP_ACTIVE
        if validation["validation_status"] in ("INCOMPLETE", "ERROR"):
            val_status = STEP_ERROR
        val_detail = validation["validation_status"].replace("_", " ").title()
    elif status == repository.STATUS_VALIDATING:
        val_status, val_detail = STEP_ACTIVE, None
    else:
        val_status, val_detail = STEP_PENDING, None
    steps.append(
        TimelineStep(key="validating", label="Validating", status=val_status, detail=val_detail)
    )

    # N+2. Package ready
    if package:
        pkg_status = STEP_COMPLETE
    elif status in (repository.STATUS_ERROR, repository.STATUS_UNSUPPORTED):
        pkg_status = STEP_ERROR
    else:
        pkg_status = STEP_PENDING
    steps.append(
        TimelineStep(key="package_ready", label="Package Ready", status=pkg_status, detail=None)
    )

    return steps


def request_detail(request: dict[str, Any]) -> AuditRequestDetail:
    request_id = request["id"]
    snapshot = repository.get_workflow_state(request_id) or {}
    state = snapshot.get("state", {}) if isinstance(snapshot, dict) else {}

    spec = get_use_case(request.get("use_case_id") or state.get("use_case_id") or "")
    parsed = repository.get_parsed_query(request_id)
    parsed_query = (parsed or {}).get("query", {})

    evidence = repository.list_retrieved_evidence(request_id)
    attempts = repository.list_retrieval_attempts(request_id)
    validation = repository.latest_validation(request_id)
    package = repository.get_package(request_id)
    review = repository.latest_review(request_id)

    required = state.get("required_evidence") or (spec.evidence_codes if spec else [])
    evidence_by_type = {item["document_type"]: item for item in evidence}

    active_search: set[str] = set()
    for attempt in attempts:
        if attempt["status"] == "SEARCHING":
            active_search.update(attempt.get("requested_evidence", []))
    retrieval_started = bool(attempts) and not any(
        attempt["status"] == "SEARCHING" for attempt in attempts
    )

    validation_status = validation.get("validation_status") if validation else None

    # --- retrieved evidence rows -----------------------------------------
    names = _database_names()
    rows: list[EvidenceRow] = []
    for item in order_by_checklist(evidence, required):
        staged = staging.resolve_staged_file(request_id, item.get("staged_file_path"))
        rows.append(
            EvidenceRow(
                evidence_id=item["id"],
                document_type=item["document_type"],
                document_type_label=(
                    spec.label_for(item["document_type"]) if spec else item["document_type"]
                ),
                identifier=item.get("identifier"),
                source_database_id=item["source_database_id"],
                source_database_name=names.get(
                    item["source_database_id"], item["source_database_id"]
                ),
                status=VALIDATED if validation_status == "COMPLETE" else FOUND,
                staged_file_path=item.get("staged_file_path"),
                has_file=bool(staged),
                row_count=(item.get("metadata") or {}).get("row_count"),
                generated=item["source_database_id"] == GENERATED_SOURCE_ID,
            )
        )

    # --- per-database attempt cards --------------------------------------
    registry = {db.database_id: db for db in enabled_databases()}
    generated_codes = set(spec.generated_codes) if spec else set()
    aggregated: dict[str, DatabaseAttemptView] = {}
    for attempt in attempts:
        requested = attempt.get("requested_evidence") or []
        # Exclude the compiled-extract row fetches, as in the timeline.
        if requested and set(requested) <= generated_codes:
            continue
        database_id = attempt["database_id"]
        spec_db = registry.get(database_id)
        existing = aggregated.get(database_id)
        newly = [
            spec.label_for(code) if spec else code
            for code in _newly_found_for(database_id, evidence, spec)
        ]
        view = DatabaseAttemptView(
            database_id=database_id,
            name=spec_db.name if spec_db else database_id,
            status="COMPLETED" if attempt["status"] == "COMPLETED" else attempt["status"],
            result_count=(existing.result_count if existing else 0) + attempt["result_count"],
            requested_evidence=attempt.get("requested_evidence", []),
            newly_found=newly,
            error_message=attempt.get("error_message") or (existing.error_message if existing else None),
            pass_number=attempt.get("pass_number", 1),
        )
        aggregated[database_id] = view

    # --- validation view --------------------------------------------------
    validation_view = None
    if validation:
        result = state.get("validation_result") or {}
        validation_view = ValidationView(
            validation_status=validation["validation_status"],
            checks=[
                ValidationCheckView(
                    code=check.get("code", ""),
                    label=check.get("label", ""),
                    result=check.get("result", "REVIEW"),
                    detail=check.get("detail"),
                )
                for check in validation.get("checks", [])
            ],
            missing_evidence=validation.get("missing_evidence", []),
            headline=result.get("headline") or validation["validation_status"].replace("_", " ").title(),
            message=result.get("message") or "",
        )

    parameters = state.get("search_parameters") or parsed_query.get("search_parameters") or {}
    if isinstance(parameters, dict):
        parameters = {k: v for k, v in parameters.items() if v not in (None, "", [])}

    return AuditRequestDetail(
        request_id=request_id,
        raw_query=request["raw_query"],
        status=request["status"],
        use_case_id=request.get("use_case_id"),
        requirement_name=request.get("requirement_name"),
        created_at=request["created_at"],
        updated_at=request["updated_at"],
        confidence=(parsed or {}).get("confidence"),
        parse_source=parsed_query.get("parse_source"),
        parameters=_parameter_views(spec, parameters) if spec else [],
        ambiguities=parsed_query.get("ambiguities") or [],
        required_evidence=_checklist(
            spec, required, evidence_by_type, validation_status, active_search, retrieval_started
        ),
        evidence_found_count=len([code for code in required if code in evidence_by_type]),
        evidence_required_count=len(required),
        retrieved_evidence=rows,
        timeline=_timeline(request, state, attempts, evidence, validation, package, spec),
        database_attempts=list(aggregated.values()),
        databases_searched=len(aggregated),
        validation=validation_view,
        retry_count=state.get("retry_count", 0),
        retry_note=state.get("retry_note"),
        missing_evidence=[
            spec.label_for(code) if spec else code
            for code in (validation.get("missing_evidence", []) if validation else [])
        ],
        package_available=bool(package),
        review_action=review.get("reviewer_action") if review else None,
        reviewer_name=review.get("reviewer_name") if review else None,
        reviewer_comment=review.get("reviewer_comment") if review else None,
        reviewed_at=review.get("created_at") if review else None,
        error_code=state.get("error_code"),
        error_message=(state.get("errors") or [None])[-1] if state.get("errors") else None,
        is_active=request["status"] in repository.ACTIVE_STATUSES,
        missing_parameters=[
            MissingParameter(**item)
            for item in required_inputs.describe(spec, state.get("missing_parameters") or [])
        ],
        clarification_question=state.get("clarification_question"),
        clarification_example=required_inputs.example_for(
            spec, state.get("missing_parameters") or []
        ),
        clarifications=state.get("clarifications") or [],
    )


def _newly_found_for(database_id: str, evidence: list[dict[str, Any]], spec) -> list[str]:
    return [
        item["document_type"]
        for item in evidence
        if item["source_database_id"] == database_id
    ]


def package_view(request: dict[str, Any]) -> PackageView:
    request_id = request["id"]
    package = repository.get_package(request_id)
    review = repository.latest_review(request_id)
    snapshot = repository.get_workflow_state(request_id) or {}
    state = snapshot.get("state", {}) if isinstance(snapshot, dict) else {}
    spec = get_use_case(request.get("use_case_id") or "")

    summary = (package or {}).get("summary", {})
    contents = [
        PackageFile(
            filename=item.get("filename") or "",
            document_type=item.get("document_type", ""),
            document_type_label=item.get("document_type_label")
            or (spec.label_for(item.get("document_type", "")) if spec else ""),
            identifier=item.get("identifier"),
            source_database_id=item.get("source_database_id", ""),
            source_database_name=_database_names().get(
                item.get("source_database_id", ""), item.get("source_database_id", "")
            ),
            status="VALIDATED" if summary.get("validation_status") == "COMPLETE" else "FOUND",
            evidence_id=None,
        )
        for item in summary.get("contents", [])
    ]

    # Match staged evidence ids onto the package rows so View still works.
    evidence = repository.list_retrieved_evidence(request_id)
    by_document = {item["document_id"]: item["id"] for item in evidence}
    for row, item in zip(contents, summary.get("contents", [])):
        row.evidence_id = by_document.get(item.get("document_id"))

    approved = request["status"] == repository.STATUS_APPROVED

    # Auditor-facing parameter labels from the catalog ("Vendor" rather than
    # the raw "vendor_name" column), so the package reads like the request.
    parameters = summary.get("extracted_inputs") or {}
    labelled = (
        [view.model_dump() for view in _parameter_views(spec, parameters)] if spec else []
    )

    return PackageView(
        request_id=request_id,
        status=request["status"],
        package_path=(package or {}).get("package_path"),
        approved=approved,
        approved_by=review.get("reviewer_name") if review and approved else None,
        approved_at=review.get("created_at") if review and approved else None,
        summary={
            **summary,
            "parameters": labelled,
            "retry_note": state.get("retry_note"),
            "reviewer_status": (review or {}).get("reviewer_action"),
        },
        contents=contents,
        trail=_trail(request, state, review),
    )


def _trail(request: dict[str, Any], state: dict[str, Any], review) -> list[TrailEntry]:
    """The retrieval and review history shown on the final package screen."""
    request_id = request["id"]
    attempts = repository.list_retrieval_attempts(request_id)
    validation = repository.latest_validation(request_id)
    parsed = repository.get_parsed_query(request_id)
    package = repository.get_package(request_id)

    entries: list[TrailEntry] = [
        TrailEntry(
            key="request_received",
            label="Request received",
            detail=f"{request_id} created",
            timestamp=request["created_at"],
        )
    ]

    if parsed:
        confidence = parsed.get("confidence")
        use_case = request.get("use_case_id") or ""
        detail = use_case
        if confidence:
            detail = f"{use_case} - {round(confidence * 100)}% confidence"
        entries.append(
            TrailEntry(
                key="query_understood",
                label="Query understood",
                detail=detail,
                timestamp=parsed.get("created_at") or request["created_at"],
            )
        )

    first_pass = [a for a in attempts if a.get("pass_number", 1) == 1]
    if first_pass:
        searched = len({a["database_id"] for a in first_pass})
        entries.append(
            TrailEntry(
                key="retrieval_started",
                label="Evidence retrieval started",
                detail=f"{searched} databases searched",
                timestamp=first_pass[0]["started_at"],
            )
        )

    retries = [a for a in attempts if a.get("pass_number", 1) > 1]
    if retries:
        recovered = [
            item["document_type"]
            for item in repository.list_retrieved_evidence(request_id)
            if item.get("pass_number", 1) > 1
        ]
        detail = (
            f"{', '.join(recovered)} found on retry" if recovered else "No further evidence found"
        )
        entries.append(
            TrailEntry(
                key="retry_performed",
                label="Retry performed",
                detail=detail,
                timestamp=retries[0]["started_at"],
            )
        )

    if validation:
        checks = validation.get("checks", [])
        passed = len([c for c in checks if c.get("result") == "PASS"])
        entries.append(
            TrailEntry(
                key="validation_complete",
                label="Validation complete",
                detail=f"{passed} of {len(checks)} checks passed",
                timestamp=validation.get("created_at"),
            )
        )

    if package:
        entries.append(
            TrailEntry(
                key="sent_for_review",
                label="Sent for review",
                detail="AP Reviewer notified",
                timestamp=package.get("created_at"),
            )
        )

    if review:
        action = review["reviewer_action"]
        label = {
            "APPROVE": "Package approved",
            "REJECT": "Package rejected",
            "RETRY": "Retry requested",
        }.get(action, action.title())
        entries.append(
            TrailEntry(
                key=f"review_{action.lower()}",
                label=label,
                detail=review.get("reviewer_name") or "AP Reviewer",
                timestamp=review["created_at"],
            )
        )

    return entries

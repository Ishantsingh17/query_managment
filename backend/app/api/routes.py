"""FastAPI routes exposing the workflow to the frontend."""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api import views
from app.schemas import (
    AuditRequestDetail,
    AuditRequestSummary,
    ClarifyRequest,
    CreateAuditRequest,
    CreateAuditResponse,
    PackageView,
    ReviewAction,
    UseCaseView,
)
from app.services import packaging, repository, runner, staging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
}


def _require_request(request_id: str) -> dict:
    request = repository.get_request(request_id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit request {request_id} was not found.",
        )
    return request


@router.get("/use-cases", response_model=list[UseCaseView])
def get_use_cases() -> list[UseCaseView]:
    """The four supported POC use cases, straight from the catalog."""
    return views.use_case_views()


@router.post(
    "/audit-requests",
    response_model=CreateAuditResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_audit_request(payload: CreateAuditRequest) -> CreateAuditResponse:
    query = payload.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A request query is required.",
        )
    request = repository.create_request(query)
    return CreateAuditResponse(request_id=request["id"], status=request["status"])


@router.get("/audit-requests", response_model=list[AuditRequestSummary])
def list_audit_requests(limit: int = 100) -> list[AuditRequestSummary]:
    """Backs the Requests list screen."""
    return [views.request_summary(request) for request in repository.list_requests(limit)]


@router.get("/audit-requests/{request_id}", response_model=AuditRequestDetail)
def get_audit_request(request_id: str) -> AuditRequestDetail:
    """The composite state the request detail screen polls."""
    return views.request_detail(_require_request(request_id))


@router.post("/audit-requests/{request_id}/run", response_model=AuditRequestDetail)
def run_audit_request(request_id: str, background: BackgroundTasks) -> AuditRequestDetail:
    """Start the workflow. Returns immediately; the UI polls for progress."""
    request = _require_request(request_id)
    if runner.is_running(request_id):
        logger.info("Run already in progress for %s", request_id)
        return views.request_detail(request)

    background.add_task(runner.run_workflow, request_id)
    return views.request_detail(request)


@router.post("/audit-requests/{request_id}/retry", response_model=AuditRequestDetail)
def retry_audit_request(request_id: str, background: BackgroundTasks) -> AuditRequestDetail:
    """Retry retrieval for whatever evidence is still missing."""
    request = _require_request(request_id)
    if runner.is_running(request_id):
        return views.request_detail(request)

    background.add_task(runner.retry_workflow, request_id)
    return views.request_detail(request)


@router.post("/audit-requests/{request_id}/clarify", response_model=AuditRequestDetail)
async def clarify_audit_request(
    request_id: str, payload: ClarifyRequest, background: BackgroundTasks
) -> AuditRequestDetail:
    """Supply the mandatory inputs a request was missing, and resume it.

    The answer is merged and re-checked inline, so the response says
    immediately whether it was enough. Only the retrieval itself is
    backgrounded, which keeps the progress timeline animating as usual.
    """
    _require_request(request_id)
    if not (payload.answer and payload.answer.strip()) and not payload.parameters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide an answer or one or more parameters.",
        )

    outcome = await runner.clarify_workflow(
        request_id, answer=payload.answer, parameters=payload.parameters
    )
    if outcome.get("resumed"):
        background.add_task(runner.resume_workflow, request_id)
    return views.request_detail(_require_request(request_id))


@router.post("/audit-requests/{request_id}/review", response_model=AuditRequestDetail)
def review_audit_request(
    request_id: str, payload: ReviewAction, background: BackgroundTasks
) -> AuditRequestDetail:
    """Record the reviewer's decision."""
    request = _require_request(request_id)

    repository.add_review(
        request_id,
        action=payload.action,
        comment=payload.comment,
        reviewer_name=payload.reviewer_name or "AP Reviewer",
    )

    if payload.action == "APPROVE":
        repository.update_request(request_id, status=repository.STATUS_APPROVED)
    elif payload.action == "REJECT":
        repository.update_request(request_id, status=repository.STATUS_REJECTED)
    else:  # RETRY
        repository.update_request(request_id, status=repository.STATUS_RETRIEVING)
        background.add_task(runner.retry_workflow, request_id)

    return views.request_detail(_require_request(request_id))


@router.get("/audit-requests/{request_id}/package", response_model=PackageView)
def get_package(request_id: str) -> PackageView:
    """Package metadata, contents and the retrieval/review trail."""
    request = _require_request(request_id)
    if repository.get_package(request_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No package has been generated for {request_id} yet.",
        )
    return views.package_view(request)


@router.get("/audit-requests/{request_id}/evidence/{evidence_id}/file")
def get_evidence_file(request_id: str, evidence_id: str) -> FileResponse:
    """Serve a staged document so the UI's View action opens the real file."""
    _require_request(request_id)
    evidence = repository.get_evidence(request_id, evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence {evidence_id} was not found for {request_id}.",
        )

    path = staging.resolve_staged_file(request_id, evidence.get("staged_file_path"))
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The staged file for this evidence item is not available.",
        )

    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/audit-requests/{request_id}/package/download")
def download_package(request_id: str) -> FileResponse:
    """Return the whole package as a single ZIP.

    This is what the Open Package action serves: the evidence directory plus
    the three JSON summaries, in one file the auditor can keep or forward.
    """
    _require_request(request_id)
    if repository.get_package(request_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No package has been generated for {request_id} yet.",
        )

    base = packaging.package_dir(request_id)
    if not base.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"The package directory for {request_id} is missing on disk.",
        )

    # Built into a temp file and deleted once the response has been sent, so
    # nothing accumulates inside the package directory itself.
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    handle.close()
    archive = Path(handle.name)

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(base.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(base).as_posix())

    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"{request_id}_audit_evidence_package.zip",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@router.get("/audit-requests/{request_id}/package/files")
def list_package_files(request_id: str) -> dict:
    """Machine-readable manifest: where the package lives and what is in it."""
    _require_request(request_id)
    package = repository.get_package(request_id)
    if package is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No package has been generated for {request_id} yet.",
        )
    base = packaging.package_dir(request_id)
    files = [
        path.relative_to(base).as_posix() for path in sorted(base.rglob("*")) if path.is_file()
    ]
    return {
        "request_id": request_id,
        "package_path": package["package_path"],
        "absolute_path": str(base),
        "files": files,
    }

"""Evidence view/open endpoints (preview inside the app without leaving it)."""
import mimetypes

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.errors import ForbiddenError, NotFoundError
from app.core.labels import evidence_label
from app.core.serializers import evidence_view, loads
from app.db.models import EvidenceItem, RequestRecord, User
from app.db.session import get_db
from app.evidence import staging
from app.mock_sources.pdf import render_pdf

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


def _load(db: Session, evidence_id: str, user: User) -> EvidenceItem:
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise NotFoundError("Evidence item not found.")
    if user.role == "AUDITOR":
        req = db.get(RequestRecord, item.request_id)
        if req.auditor_id != user.user_id or not item.is_approved:
            raise ForbiddenError("This evidence becomes available once the SME approves the package.")
    return item


@router.get("/{evidence_id}")
def view(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = _load(db, evidence_id, user)
    payload = loads(item.normalized_payload_json)
    return {**evidence_view(item), "request_id": item.request_id,
            "record": payload.get("normalized_payload", {}).get("record"),
            "records": payload.get("normalized_payload", {}).get("records", []),
            "provenance": {k: payload.get("metadata", {}).get(k) for k in ("endpoint", "keys_used", "retrieval_role", "attempts",
                                                                            "expected_output_type", "original_filename")},
            "retrieved_at": payload.get("retrieved_at")}


@router.get("/{evidence_id}/file")
def open_file(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = _load(db, evidence_id, user)
    if item.file_path:
        path = staging.absolute(item.file_path)
        if path.exists():
            media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return FileResponse(path, media_type=media, headers={"Content-Disposition": f'inline; filename="{path.name}"'})
    record = loads(item.normalized_payload_json).get("normalized_payload", {}).get("record")
    if not record:
        raise NotFoundError("No file or record is available for this evidence item.")
    pdf = render_pdf(f"{evidence_label(item.evidence_type)} · {item.source_reference}",
                     f"Source system: {item.source_system} · retrieved via API", [(k.replace('_', ' ').title(), v) for k, v in record.items()],
                     footer=f"Canonical evidence {item.evidence_id} · Audit Evidence Platform")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{item.source_reference}.pdf"'})

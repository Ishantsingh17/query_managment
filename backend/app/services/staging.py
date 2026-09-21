"""Evidence staging.

Retrieved documents are copied into a per-request staging area alongside the
metadata that says where each one came from. Source documents are only ever
read, never modified or moved.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.config import get_settings

# Filename prefixes per evidence type. These reproduce the names shown in the
# package contents of the UI mockups (Invoice_INV-12345.pdf, PO_PO-5678.pdf,
# Supporting_Document_01.pdf, ...).
_PREFIXES = {
    "INVOICE": "Invoice",
    "PURCHASE_ORDER": "PO",
    "GRN": "GRN",
    "SES": "SES",
    "SUPPORTING_DOCUMENT": "Supporting_Document",
    "BALANCE_CONFIRMATION_LETTER": "Balance_Confirmation_Letter",
}

# Words that must keep their case when a document type is title-cased, so
# GL_DUMP becomes GL_Dump rather than Gl_Dump, and APTB stays APTB.
_ACRONYMS = {"GL", "AP", "AR", "APTB", "PO", "GRN", "SES", "NAC", "SOB"}


def _title_case_type(document_type: str) -> str:
    return "_".join(
        part if part in _ACRONYMS else part.title() for part in document_type.split("_")
    )

# Types named by sequence rather than by their raw identifier, so SUPP-01
# becomes Supporting_Document_01.
_NUMERIC_SUFFIX_TYPES = {"SUPPORTING_DOCUMENT"}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(text: str) -> str:
    return _UNSAFE.sub("_", text).strip("_")


def staged_filename(document_type: str, identifier: str | None, extension: str) -> str:
    """Deterministic, human-readable filename for a staged document."""
    prefix = _PREFIXES.get(document_type) or _title_case_type(document_type)
    identifier = (identifier or "").strip()

    if document_type in _NUMERIC_SUFFIX_TYPES:
        digits = re.findall(r"\d+", identifier)
        suffix = digits[-1] if digits else "01"
    else:
        suffix = identifier or "document"

    return f"{_safe(prefix)}_{_safe(suffix)}{extension}"


def request_staging_dir(request_id: str) -> Path:
    return get_settings().evidence_staging_dir / request_id


def ensure_staging(request_id: str) -> dict[str, Path]:
    """Create evidence_staging/{request_id}/{retrieved,metadata,validation}."""
    base = request_staging_dir(request_id)
    paths = {
        "base": base,
        "retrieved": base / "retrieved",
        "metadata": base / "metadata",
        "validation": base / "validation",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def stage_document(
    request_id: str,
    *,
    document_id: str,
    document_type: str,
    identifier: str | None,
    source_absolute_path: str | None,
    source_relative_path: str | None,
    source_database_id: str,
    metadata: dict[str, Any] | None,
    matched_on: list[str] | None = None,
) -> dict[str, Any]:
    """Copy one document into staging and write its provenance sidecar.

    Returns the staged relative path plus whether the copy succeeded.
    """
    paths = ensure_staging(request_id)
    settings = get_settings()

    source = Path(source_absolute_path) if source_absolute_path else None
    extension = source.suffix if source and source.suffix else ".pdf"
    filename = staged_filename(document_type, identifier, extension)
    destination = paths["retrieved"] / filename

    copied = False
    error: str | None = None
    if source and source.exists():
        try:
            # copy2 preserves the source mtime on the copy and never touches
            # the original.
            shutil.copy2(source, destination)
            copied = True
        except OSError as exc:
            error = f"Could not stage {document_id}: {exc}"
    else:
        error = f"Source file for {document_id} was not found."

    sidecar = {
        "request_id": request_id,
        "document_id": document_id,
        "document_type": document_type,
        "identifier": identifier,
        "source_database_id": source_database_id,
        "source_file_path": source_relative_path,
        "staged_file_path": (
            str(destination.relative_to(settings.data_root).as_posix()) if copied else None
        ),
        "staged_filename": filename if copied else None,
        "matched_on": matched_on or [],
        "metadata": metadata or {},
        "staging_error": error,
    }
    (paths["metadata"] / f"{filename}.json").write_text(
        json.dumps(sidecar, indent=2, default=str), encoding="utf-8"
    )

    return {
        "staged": copied,
        "staged_filename": filename if copied else None,
        "staged_file_path": sidecar["staged_file_path"],
        "error": error,
    }


def write_validation_snapshot(request_id: str, payload: dict[str, Any]) -> Path:
    """Persist the validation outcome next to the staged evidence."""
    paths = ensure_staging(request_id)
    target = paths["validation"] / "validation.json"
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return target


def resolve_staged_file(request_id: str, staged_file_path: str | None) -> Path | None:
    """Resolve a staged path safely, refusing anything outside the request dir."""
    if not staged_file_path:
        return None
    settings = get_settings()
    candidate = (settings.data_root / staged_file_path).resolve()
    root = request_staging_dir(request_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.exists() else None

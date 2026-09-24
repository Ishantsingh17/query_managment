"""Evidence Review Package (pre-approval) and Final Response Package (post-approval) assembly.
Both are owned by the Orchestrator; this module only builds and persists them."""
import hashlib
import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.labels import query_type_label
from app.core.models import EvidenceReviewPackage, FinalResponsePackage, ValidationResult
from app.core.serializers import evidence_view, iso, loads
from app.db.models import EvidenceItem, RequestRecord
from app.evidence import staging

APPROVABLE = ("AVAILABLE", "MANUALLY_UPLOADED")


class PackageError(RuntimeError):
    pass


def package_dir(request_id: str) -> Path:
    d = get_settings().packages_dir / request_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def build_review_package(request: RequestRecord, items: list[EvidenceItem], validation: ValidationResult,
                         validated_by: str, validator_note: str | None) -> EvidenceReviewPackage:
    d = package_dir(request.request_id)
    version = len(list(d.glob("evidence_review_package_v*.json"))) + 1
    sq = loads(request.structured_query_json)
    exceptions = [
        {"evidence_type": i.evidence_type, "type": "ACCEPTED_NOT_REQUIRED", "justification": evidence_view(i)["justification"]}
        for i in items if i.validation_status == "NOT_REQUIRED"
    ] + [
        {"evidence_type": i.evidence_type, "type": "MANUALLY_UPLOADED", "uploaded_by": evidence_view(i)["uploaded_by"]}
        for i in items if i.validation_status == "MANUALLY_UPLOADED"
    ]
    path = d / "evidence_review_package.json"
    pkg = EvidenceReviewPackage(
        request_id=request.request_id, version=version,
        request_summary={
            "request_id": request.request_id, "original_query": request.original_query,
            "query_type": request.query_type, "query_type_label": query_type_label(request.query_type),
            "parameters": sq.get("parameters", {}), "auditor_id": request.auditor_id,
            "created_at": iso(request.created_at), "validated_by": validated_by, "validator_note": validator_note,
        },
        evidence_items=[evidence_view(i) for i in items], validation_result=validation,
        exceptions=exceptions, package_path=staging.relative(path), created_at=datetime.now(timezone.utc),
    )
    data = pkg.model_dump(mode="json")
    _write_json(path, data)
    _write_json(d / f"evidence_review_package_v{version}.json", data)
    return pkg


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_final_package(request: RequestRecord, items: list[EvidenceItem], approval: dict) -> FinalResponsePackage:
    approved = [i for i in items if i.is_approved and i.validation_status in APPROVABLE]
    if not approved:
        raise PackageError("No SME-approved evidence available to package")
    d = package_dir(request.request_id)
    support = d / "supporting_files"
    support.mkdir(exist_ok=True)

    evidence_entries = []
    for i in approved:
        entry = evidence_view(i)
        if i.file_path:
            src = staging.absolute(i.file_path)
            if not src.exists():
                raise PackageError(f"Evidence file for {entry['label']} is missing from staging")
            dst = support / f"{i.evidence_type}_{src.name}"
            shutil.copy2(src, dst)
            entry["package_file"] = staging.relative(dst)
            entry["sha256"] = _sha256_file(dst)
        else:
            entry["normalized_record"] = loads(i.normalized_payload_json).get("normalized_payload", {}).get("record")
        evidence_entries.append(entry)

    body = json.dumps(evidence_entries, sort_keys=True, default=str).encode()
    checksum = hashlib.sha256(body).hexdigest()
    path = d / "final_response_package.json"
    pkg = FinalResponsePackage(
        request_id=request.request_id, approved_evidence=evidence_entries,
        response_metadata={
            "query_type": request.query_type, "query_type_label": query_type_label(request.query_type),
            "original_query": request.original_query, "approval": approval, "sealed": True,
        },
        package_path=staging.relative(path), checksum=checksum, created_at=datetime.now(timezone.utc),
    )
    _write_json(path, pkg.model_dump(mode="json"))
    return pkg


def load_package(rel_path: str | None) -> dict | None:
    if not rel_path:
        return None
    p = staging.absolute(rel_path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def bundle_zip(request_id: str) -> bytes:
    d = package_dir(request_id)
    final = d / "final_response_package.json"
    if not final.exists():
        raise PackageError("Final Response Package has not been generated yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(final, "final_response_package.json")
        for f in sorted((d / "supporting_files").glob("*")):
            z.write(f, f"supporting_files/{f.name}")
    return buf.getvalue()

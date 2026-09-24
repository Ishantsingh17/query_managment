"""Normalization -> Canonical Evidence Model, preserving source attribution and provenance."""
import json
import uuid
from datetime import datetime, timezone

from app.agents.retrieval_agent import RawEvidence
from app.core.models import CanonicalEvidence
from app.evidence import staging
from app.evidence.extraction import ExtractedContent, extractor_for

_DOC_NOUN = {
    "INVOICE": "Invoice", "PO": "PO", "GRN_SES": "GRN/SES", "APPROVAL": "Signed approval",
    "PAYMENT_REPORT": "Payment report", "PAYMENT_ADVICE_UTR": "Payment advice", "ACCOUNTING_ENTRY": "Journal line",
    "VENDOR_PAYABLE_BALANCE": "Balance", "AGEING": "Ageing", "APTB_LEDGER_EXTRACT": "APTB extract",
    "VENDOR_CONTACT_DETAILS": "Contact", "SIGNED_CONFIRMATION_LETTER": "Confirmation letter",
    "SIGNATORY_EMAIL_APPROVAL": "Signatory email approval", "IPAMS_APPROVAL": "Signed approval",
    "BOARD_RESOLUTION_LIMITS": "Board resolution",
}


def new_evidence_id() -> str:
    return f"EV-{uuid.uuid4().hex[:10].upper()}"


def describe(evidence_type: str, ex: ExtractedContent, record: dict, corroborated: bool) -> str:
    noun = _DOC_NOUN.get(evidence_type, "Evidence")
    if ex.payload_type == "PDF":
        kind = "scan" if evidence_type == "GRN_SES" else "PDF"
        if evidence_type in ("APPROVAL", "IPAMS_APPROVAL", "SIGNATORY_EMAIL_APPROVAL"):
            return f"{noun} · {ex.pages} page{'s' if ex.pages != 1 else ''} · {ex.size_kb} KB"
        return f"{noun} {kind} · {ex.pages} page{'s' if ex.pages != 1 else ''} · {ex.size_kb} KB"
    if ex.payload_type == "IMAGE":
        return f"{noun} scans · {record.get('receipt_count', ex.pages)} images · {ex.size_kb} KB"
    if ex.payload_type == "CSV":
        return f"{noun} · {len(ex.records)} entr{'ies' if len(ex.records) != 1 else 'y'} · CSV"
    parts = [f"{noun} record" if len(ex.records) == 1 else f"{len(ex.records)} {noun.lower()} records"]
    for k in ("revision", "utr", "payment_run_id"):
        if record.get(k):
            parts.append(f"UTR {record[k]}" if k == "utr" else str(record[k]))
    if corroborated:
        parts.append("matched")
    return " · ".join(parts)


def normalize(request_id: str, raw: RawEvidence) -> CanonicalEvidence:
    assert raw.found and raw.result and raw.step
    res, step = raw.result, raw.step
    ex = extractor_for(step.expected_output_type).extract(res.records, res.documents, res.reference_field)
    first = res.records[0]
    reference = str(first.get(res.reference_field) or "")
    evidence_id = new_evidence_id()

    # Retain the original response and file.
    staging.write_original(request_id, f"{raw.evidence_type}_{res.source_system}_response.json",
                           json.dumps(res.records, indent=2, default=str).encode())
    original_path = None
    if ex.file_bytes:
        original_path = staging.relative(
            staging.write_original(request_id, f"{raw.evidence_type}_{reference}{ex.file_ext}", ex.file_bytes))

    corroborated = any(c.get("matched") for c in raw.corroboration)
    metadata = {
        "description": describe(raw.evidence_type, ex, first, corroborated),
        "pages": ex.pages, "size_kb": ex.size_kb, "record_count": len(res.records),
        "keys_used": raw.keys_used, "endpoint": res.endpoint, "retrieval_role": step.role,
        "attempts": raw.attempts, "corroboration": raw.corroboration, "notes": raw.notes,
        "expected_output_type": step.expected_output_type,
    }
    records = [{k: v for k, v in r.items() if k != "document_url"} for r in res.records]
    evidence = CanonicalEvidence(
        evidence_id=evidence_id, request_id=request_id, evidence_type=raw.evidence_type,
        source_system=res.source_system, source_reference=reference if len(records) == 1 else f"{reference} +{len(records) - 1}",
        payload_type=ex.payload_type, normalized_payload={"record": records[0], "records": records},
        original_file_path=original_path, retrieved_at=datetime.now(timezone.utc), metadata=metadata,
    )
    staging.write_normalized(request_id, evidence_id, evidence.model_dump(mode="json"))
    return evidence

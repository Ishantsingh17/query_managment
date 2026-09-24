"""Mock source APIs. These mirror the future enterprise API contracts:

    GET  /mock-api/{source}/{object-path}?{key}={value}        -> 200 {source_system, object, count, records[]}
                                                                  404 no matching record, 503 source unavailable
    GET  /mock-api/{source}/{object-path}/{reference}/document -> application/pdf
    POST /mock-api/_admin/sources/{source}/availability        -> toggle outage simulation (dev/test only)
    POST /mock-api/_admin/reset-late-postings                  -> re-arm "posted late" records (dev/test only)
"""
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.core.config import get_settings
from app.mock_sources import store
from app.mock_sources.datasets import OBJECTS, SOURCE_SYSTEMS, find_spec
from app.mock_sources.pdf import render_pdf

router = APIRouter(prefix="/mock-api", tags=["mock-source-apis"])


def _latency():
    ms = get_settings().mock_latency_ms
    if ms > 0:
        time.sleep(ms / 1000)


@router.get("/_admin/sources")
def admin_sources():
    return store.list_sources()


@router.post("/_admin/sources/{source}/availability")
def admin_set_availability(source: str, available: bool):
    if source.upper() not in SOURCE_SYSTEMS:
        raise HTTPException(404, "Unknown source system")
    store.set_source_available(source.upper(), available)
    return {"source_system": source.upper(), "available": available}


@router.post("/_admin/reset-late-postings")
def admin_reset_late_postings():
    """Dev/test: make 'posted late' records unavailable again for their first lookup."""
    store.reset_late_postings()
    return {"reset": True}


@router.get("/{source}/{object_path:path}")
def source_lookup(source: str, object_path: str, request: Request):
    source = source.upper()
    if source not in SOURCE_SYSTEMS:
        raise HTTPException(404, f"Unknown source system {source}")
    if not store.is_source_available(source):
        raise HTTPException(503, f"{source} is temporarily unavailable")
    _latency()

    if object_path.endswith("/document"):
        base, ref = object_path.removesuffix("/document").rsplit("/", 1)
        spec = find_spec(source, base)
        if not spec or not spec.document:
            raise HTTPException(404, "Document endpoint not available for this object")
        record = store.get_by_ref(spec, ref)
        if not record:
            raise HTTPException(404, f"No document {ref} in {source}")
        pdf = render_pdf(
            title=f"{source} · {ref}",
            subtitle=f"{SOURCE_SYSTEMS[source]} — {spec.path.strip('/').replace('-', ' ').title()}",
            fields=[(k.replace("_", " ").title(), v) for k, v in record.items()],
            footer="Mock source document generated for development and integration testing.",
        )
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{ref}.pdf"'})

    spec = find_spec(source, object_path)
    if not spec:
        raise HTTPException(404, f"Unknown object /{object_path} for {source}")
    filters = {k: v for k, v in request.query_params.items() if k in spec.lookup_keys and v}
    if not filters:
        raise HTTPException(400, f"Provide one of: {', '.join(spec.lookup_keys)}")
    records = store.query(spec, filters, request.headers.get("x-request-id"))
    if not records:
        raise HTTPException(404, f"No {spec.path.strip('/')} found in {source} for {filters}")
    for r in records:
        if spec.document:
            r["document_url"] = f"/mock-api/{source.lower()}{spec.path}/{r[spec.ref_field]}/document"
    return {"source_system": source, "object": spec.path, "reference_field": spec.ref_field,
            "count": len(records), "records": records}


def describe_objects() -> list[dict]:
    return [{"source_system": s.source, "path": s.path, "lookup_keys": list(s.lookup_keys), "document": s.document}
            for s in OBJECTS]

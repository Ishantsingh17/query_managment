"""Source-specific connectors. Each wraps one enterprise source API behind a stable contract.

Swapping mock -> real APIs (Implementation Plan step 14) means changing a connector's base URL/auth
only; the MCP tool contract and the Retrieval Agent stay unchanged.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)


@dataclass
class ConnectorResult:
    ok: bool
    source_system: str
    records: list[dict[str, Any]] = field(default_factory=list)
    reference_field: str | None = None
    documents: dict[str, bytes] = field(default_factory=dict)  # reference -> bytes
    status_code: int | None = None
    error: str | None = None
    endpoint: str | None = None

    @property
    def source_error(self) -> bool:
        """True when the source itself failed (retry may help), as opposed to 'no record'."""
        return not self.ok and (self.status_code is None or self.status_code >= 500)

    @property
    def error_kind(self) -> str | None:
        """Short error class for logs/telemetry: SourceUnreachable | HTTP_<code> | None."""
        if self.ok:
            return None
        return "SourceUnreachable" if self.status_code is None else f"HTTP_{self.status_code}"


class SourceConnector:
    source_system: str = ""
    base_path: str = ""

    def __init__(self, client: httpx.Client):
        self.client = client

    def auth_headers(self) -> dict[str, str]:
        # Controlled credentials placeholder; real connectors inject per-source auth here.
        return {"X-Client": "audit-evidence-platform"}

    def retrieve(self, path: str, keys: dict[str, Any], include_documents: bool = True,
                 request_id: str | None = None) -> ConnectorResult:
        url = f"{self.base_path}{path}"
        params = {k: v for k, v in keys.items() if v not in (None, "")}
        headers = {**self.auth_headers(), **({"X-Request-ID": request_id} if request_id else {})}
        try:
            resp = self.client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("connector transport error", extra={"source_system": self.source_system})
            return ConnectorResult(False, self.source_system, error=f"{self.source_system} could not be reached ({exc.__class__.__name__})", endpoint=url)
        if resp.status_code != 200:
            detail = _detail(resp)
            return ConnectorResult(False, self.source_system, status_code=resp.status_code, error=detail, endpoint=url)
        body = resp.json()
        result = ConnectorResult(True, self.source_system, records=body.get("records", []),
                                 reference_field=body.get("reference_field"), status_code=200, endpoint=url)
        if include_documents:
            for rec in result.records:
                doc_url = rec.get("document_url")
                if not doc_url:
                    continue
                try:
                    d = self.client.get(doc_url, headers=self.auth_headers())
                    if d.status_code == 200:
                        result.documents[str(rec.get(result.reference_field))] = d.content
                except httpx.HTTPError:
                    log.warning("document download failed", extra={"source_system": self.source_system})
        return result


def _detail(resp: httpx.Response) -> str:
    try:
        return resp.json().get("detail") or resp.text
    except ValueError:
        return resp.text or f"HTTP {resp.status_code}"


def _make(name: str) -> type[SourceConnector]:
    return type(f"{name.title()}Connector", (SourceConnector,), {"source_system": name, "base_path": f"/mock-api/{name.lower()}"})


# One logical integration per enterprise application.
OracleConnector = _make("ORACLE")
GrsConnector = _make("GRS")
VmsConnector = _make("VMS")
GessConnector = _make("GESS")
LmsConnector = _make("LMS")
AribaConnector = _make("ARIBA")
GpsConnector = _make("GPS")
GrossConnector = _make("GROSS")
IpamsConnector = _make("IPAMS")

CONNECTOR_CLASSES: dict[str, type[SourceConnector]] = {
    c.source_system: c for c in (OracleConnector, GrsConnector, VmsConnector, GessConnector, LmsConnector,
                                 AribaConnector, GpsConnector, GrossConnector, IpamsConnector)
}

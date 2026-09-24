"""MCP gateway: the only path from the Retrieval Agent to source systems.

Exposes one tool per source system (`<source>_retrieve_evidence`) with a JSON-schema contract,
following MCP's tools/list + tools/call shape. The same gateway is served over HTTP JSON-RPC at /mcp.
"""
import logging
from typing import Any

import httpx
from observability import get_observability

from app.core.config import get_settings
from app.mcp.connectors import CONNECTOR_CLASSES, ConnectorResult, SourceConnector

log = logging.getLogger(__name__)

TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "description": "Source object path, e.g. /invoices"},
        "keys": {"type": "object", "description": "Search / retrieval keys", "additionalProperties": {"type": "string"}},
        "include_documents": {"type": "boolean", "default": True},
        "request_id": {"type": "string", "description": "Optional correlation id, forwarded to the source as X-Request-ID"},
    },
    "required": ["operation", "keys"],
}


class McpGateway:
    def __init__(self, client: httpx.Client | None = None):
        settings = get_settings()
        self._client = client or httpx.Client(base_url=settings.source_api_base_url,
                                              timeout=settings.source_api_timeout_seconds)
        self._connectors: dict[str, SourceConnector] = {name: cls(self._client) for name, cls in CONNECTOR_CLASSES.items()}

    @staticmethod
    def tool_name(source_system: str) -> str:
        return f"{source_system.lower()}_retrieve_evidence"

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": self.tool_name(s), "description": f"Retrieve evidence records and documents from {s} via its source API.",
             "inputSchema": TOOL_INPUT_SCHEMA}
            for s in self._connectors
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ConnectorResult:
        source = name.removesuffix("_retrieve_evidence").upper()
        keys = arguments.get("keys", {}) or {}
        with get_observability().tool_call(name, connector=source, component="mcp_gateway",
                                           operation=arguments.get("operation"),
                                           inputs={"operation": arguments.get("operation"), "keys": keys,
                                                   "include_documents": arguments.get("include_documents", True)}) as tool:
            connector = self._connectors.get(source)
            if connector is None:
                tool.set_result(False, "UnknownConnector", f"No MCP connector registered for {source}")
                return ConnectorResult(False, source, status_code=404, error=f"No MCP connector registered for {source}")
            log.info("mcp tool call", extra={"source_system": source, "event": name})
            res = connector.retrieve(arguments["operation"], keys, arguments.get("include_documents", True),
                                     arguments.get("request_id"))
            # "no record" (404) is a successful tool call with found=false; only source failures are tool failures
            tool.set_result(not res.source_error, error_type=res.error_kind, error_message=res.error,
                            found=bool(res.ok and res.records), record_count=len(res.records),
                            document_count=len(res.documents), status_code=res.status_code, key_names=sorted(keys))
            tool.set_outputs({"ok": res.ok, "records": res.records, "reference_field": res.reference_field})
            return res


_gateway: McpGateway | None = None


def get_gateway() -> McpGateway:
    global _gateway
    if _gateway is None:
        _gateway = McpGateway()
    return _gateway


def set_gateway(gw: McpGateway | None) -> None:
    global _gateway
    _gateway = gw

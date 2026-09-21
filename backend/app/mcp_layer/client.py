"""MCP client wrapper.

Speaks the real MCP protocol to the tool server over an in-memory transport,
so tool calls are genuine JSON-RPC round trips without a subprocess to
supervise. Agents depend only on this surface and never import sqlite3.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp.shared.memory import create_connected_server_and_client_session

from app.mcp_layer.server import mcp_server

# The low-level server logs every request at INFO; quiet it so demo logs stay
# readable without suppressing genuine warnings.
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

SEARCH_TOOL = "search_sqlite_database"
FETCH_TRANSACTIONS_TOOL = "fetch_transactions"
METADATA_TOOL = "get_document_metadata"
RETRIEVE_TOOL = "retrieve_document"


class ToolCallRecord:
    """One recorded MCP tool invocation, for the retrieval audit log."""

    __slots__ = ("tool", "arguments", "status", "error_message")

    def __init__(self, tool: str, arguments: dict, status: str, error_message: str | None):
        self.tool = tool
        self.arguments = arguments
        self.status = status
        self.error_message = error_message

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "status": self.status,
            "error_message": self.error_message,
        }


class AuditMcpClient:
    """Thin, typed facade over the MCP session."""

    def __init__(self, session):
        self._session = session
        self.calls: list[ToolCallRecord] = []

    async def _call(self, tool: str, arguments: dict) -> dict[str, Any]:
        try:
            result = await self._session.call_tool(tool, arguments)
        except Exception as exc:  # transport/protocol failure
            payload = {
                "status": "ERROR",
                "error_code": "RETRIEVAL_ERROR",
                "error_message": f"MCP call to {tool} failed: {exc}",
            }
            self.calls.append(ToolCallRecord(tool, arguments, "ERROR", payload["error_message"]))
            return payload

        if getattr(result, "isError", False):
            message = _first_text(result) or f"MCP tool {tool} reported an error."
            payload = {
                "status": "ERROR",
                "error_code": "RETRIEVAL_ERROR",
                "error_message": message,
            }
            self.calls.append(ToolCallRecord(tool, arguments, "ERROR", message))
            return payload

        text = _first_text(result)
        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            payload = {
                "status": "ERROR",
                "error_code": "RETRIEVAL_ERROR",
                "error_message": f"MCP tool {tool} returned a non-JSON payload.",
            }

        self.calls.append(
            ToolCallRecord(
                tool,
                arguments,
                str(payload.get("status", "SUCCESS")),
                payload.get("error_message"),
            )
        )
        return payload

    async def search_database(
        self,
        database_id: str,
        required_evidence: list[str],
        search_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._call(
            SEARCH_TOOL,
            {
                "database_id": database_id,
                "required_evidence": list(required_evidence),
                "search_parameters": dict(search_parameters),
            },
        )

    async def fetch_transactions(
        self,
        database_id: str,
        search_parameters: dict[str, Any],
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._call(
            FETCH_TRANSACTIONS_TOOL,
            {
                "database_id": database_id,
                "search_parameters": dict(search_parameters),
                "filters": dict(filters or {}),
            },
        )

    async def get_document_metadata(self, database_id: str, document_id: str) -> dict[str, Any]:
        return await self._call(
            METADATA_TOOL, {"database_id": database_id, "document_id": document_id}
        )

    async def retrieve_document(self, database_id: str, document_id: str) -> dict[str, Any]:
        return await self._call(
            RETRIEVE_TOOL, {"database_id": database_id, "document_id": document_id}
        )

    async def list_tools(self) -> list[str]:
        result = await self._session.list_tools()
        return [tool.name for tool in result.tools]


def _first_text(result) -> str | None:
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return None


@asynccontextmanager
async def open_mcp_client() -> AsyncIterator[AuditMcpClient]:
    """Open an MCP session for the duration of a retrieval pass."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        yield AuditMcpClient(session)

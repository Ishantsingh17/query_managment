"""MCP gateway over HTTP JSON-RPC (tools/list, tools/call) for inspection and connector contract tests."""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_role
from app.mcp.gateway import get_gateway

router = APIRouter(tags=["mcp"])


class JsonRpc(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] = {}


@router.post("/mcp")
def mcp(body: JsonRpc, _=Depends(require_role("VALIDATOR", "SME"))):
    gw = get_gateway()
    if body.method == "tools/list":
        return {"jsonrpc": "2.0", "id": body.id, "result": {"tools": gw.list_tools()}}
    if body.method == "tools/call":
        res = gw.call_tool(body.params.get("name", ""), body.params.get("arguments", {}))
        return {"jsonrpc": "2.0", "id": body.id, "result": {
            "isError": not res.ok,
            "structuredContent": {"source_system": res.source_system, "records": res.records, "error": res.error,
                                  "status_code": res.status_code, "documents": list(res.documents)},
        }}
    return {"jsonrpc": "2.0", "id": body.id, "error": {"code": -32601, "message": "Method not found"}}

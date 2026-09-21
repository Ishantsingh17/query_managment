"""Diagnostic: replay the UC-04 sequential search through the MCP layer.

Proves the first pass genuinely misses SES and the retry pass finds it.
Run: python scripts/probe_search.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog.loader import enabled_databases, required_evidence_for  # noqa: E402
from app.mcp_layer.client import open_mcp_client  # noqa: E402


async def run_pass(client, label, required, context):
    print(f"\n=== {label} ===")
    print(f"context: {context}")
    found: dict[str, str] = {}

    for spec in enabled_databases():
        missing = [code for code in required if code not in found]
        if not missing:
            print(f"  {spec.database_id}: skipped - nothing missing")
            continue

        result = await client.search_database(spec.database_id, missing, context)
        if result.get("status") != "SUCCESS":
            print(f"  {spec.database_id}: {result.get('error_code')} - {result.get('error_message')}")
            continue

        matches = result.get("matches", [])
        names = [f"{m['document_type']}({m['identifier']})" for m in matches]
        print(f"  {spec.database_id}: searched for {missing} -> {len(matches)} match(es) {names}")

        for match in matches:
            found[match["document_type"]] = match["identifier"]

        discovered = result.get("discovered_identifiers", {})
        new_keys = {k: v for k, v in discovered.items() if context.get(k) != v}
        if new_keys:
            print(f"      discovered identifiers -> {new_keys}")
            context.update(new_keys)

    missing = [code for code in required if code not in found]
    print(f"  RESULT found={sorted(found)} missing={missing}")
    return found, missing, context


async def main():
    required = required_evidence_for("UC-04")
    context = {"vendor_name": "ABC Ltd", "invoice_number": "INV-12345"}

    async with open_mcp_client() as client:
        print("MCP tools exposed:", await client.list_tools())

        found, missing, context = await run_pass(client, "PASS 1 (initial retrieval)", required, context)

        if not missing:
            print("\nFAIL: expected SES to be missing after pass 1 - the retry would never fire.")
            return 1

        found2, missing2, _ = await run_pass(
            client, "PASS 2 (retry with enriched context)", missing, context
        )
        found.update(found2)

        print("\n=== OUTCOME ===")
        print(f"retry_count = 1")
        print(f"found: {found}")
        print(f"still missing: {missing2}")

        if missing2:
            print("\nFAIL: SES was not recovered on retry.")
            return 1
        if missing != ["SES"]:
            print(f"\nFAIL: expected exactly ['SES'] missing after pass 1, got {missing}.")
            return 1

        print("\nPASS: SES missed on pass 1, recovered on retry via discovered ses_number.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

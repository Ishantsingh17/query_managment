"""Retrieval Agent.

Coordinates the sequential, multi-database evidence search. It knows nothing
about which system holds which evidence: it walks the configured sources in
order, asks each one only for what is still missing, and folds any strong
identifiers it discovers into the search context so later sources can be
queried with keys the original request never contained.

All data access goes through the MCP client - this module never imports
sqlite3.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.catalog.loader import enabled_databases, get_use_case
from app.config import get_settings
from app.mcp_layer.client import open_mcp_client
from app.services import repository, staging, tabular

logger = logging.getLogger(__name__)

ProgressHook = Callable[[dict[str, Any]], Awaitable[None]] | None

# Evidence compiled from several systems has no single source database.
GENERATED_SOURCE_ID = "GENERATED"

# Identifier columns copied onto each evidence record. The Validation Engine
# compares these against the auditor's stated parameters, so they have to
# travel with the evidence rather than staying behind in the source row.
_EVIDENCE_FIELDS = (
    "vendor_id", "vendor_name", "invoice_number", "po_number", "grn_number",
    "ses_number", "account_number", "sob", "nac_code", "period", "report_type",
)


@dataclass
class RetrievalOutcome:
    """Result of one retrieval pass."""

    found: dict[str, dict[str, Any]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Search context after enrichment, carried into the next pass.
    context: dict[str, Any] = field(default_factory=dict)
    # identifier key -> database that revealed it (e.g. ses_number -> DB-04).
    identifier_origin: dict[str, str] = field(default_factory=dict)
    # evidence code -> database whose identifier unlocked it.
    unlocked_by: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "missing": self.missing,
            "attempts": self.attempts,
            "errors": self.errors,
            "identifier_origin": self.identifier_origin,
            "unlocked_by": self.unlocked_by,
        }


async def _pace() -> None:
    """Pause between sources so the sequential search is visible in the UI."""
    delay_ms = get_settings().demo_step_delay_ms
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)


async def retrieve_evidence(
    request_id: str,
    use_case_id: str,
    required_evidence: list[str],
    search_context: dict[str, Any],
    *,
    already_found: dict[str, dict[str, Any]] | None = None,
    identifier_origin: dict[str, str] | None = None,
    scope_context: dict[str, Any] | None = None,
    tabular_filters: dict[str, Any] | None = None,
    pass_number: int = 1,
    progress: ProgressHook = None,
) -> RetrievalOutcome:
    """Search the configured databases in order for the required evidence.

    Args:
        required_evidence: evidence codes still wanted for this pass.
        search_context: MCP-facing search parameters, enriched as we go.
        already_found: evidence located by earlier passes, so it is skipped.
        identifier_origin: where previously discovered identifiers came from.
        scope_context: the auditor's STATED scope, never enriched. Aggregate
            evidence must be compiled against this rather than the enriched
            context: an identifier discovered mid-run (a vendor id harvested
            from one row) would silently narrow the population, turning a
            full transaction listing into an arbitrary subset of itself.
        tabular_filters: extra exact-match narrowing for compiled evidence
            only, on columns the shared matcher ignores. An AP cost drill
            still requires the AP, AR and Others report DOCUMENTS, so the
            matcher cannot filter on report_type - but the transaction
            listing behind that request should hold AP lines only.
        pass_number: 1 for the initial pass, 2+ for retries.
    """
    outcome = RetrievalOutcome(
        found=dict(already_found or {}),
        context=dict(search_context),
        identifier_origin=dict(identifier_origin or {}),
    )
    spec = get_use_case(use_case_id)

    # Human-judgement items can never be satisfied by a search, and generated
    # items are compiled from row data rather than found as documents.
    human_required = {item.code for item in (spec.evidence if spec else []) if item.human_required}
    generated = {item.code for item in (spec.evidence if spec else []) if item.generated}
    searchable = [
        code
        for code in required_evidence
        if code not in human_required and code not in generated
    ]
    wanted_generated = [code for code in required_evidence if code in generated]

    async with open_mcp_client() as client:
        for database in enabled_databases():
            wanted = [code for code in searchable if code not in outcome.found]
            if not wanted:
                logger.info("Nothing outstanding; skipping %s", database.database_id)
                break

            if progress:
                await progress(
                    {
                        "event": "database_search_started",
                        "database_id": database.database_id,
                        "database_name": database.name,
                        "requested_evidence": wanted,
                        "pass_number": pass_number,
                    }
                )
            await _pace()

            attempt_id = repository.start_retrieval_attempt(
                request_id=request_id,
                database_id=database.database_id,
                search_parameters=outcome.context,
                requested_evidence=wanted,
                pass_number=pass_number,
            )

            result = await client.search_database(database.database_id, wanted, outcome.context)

            if result.get("status") != "SUCCESS":
                message = result.get("error_message") or "Search failed."
                error_code = result.get("error_code") or "ERROR"
                outcome.errors.append(f"{database.database_id}: {message}")
                repository.complete_retrieval_attempt(attempt_id, 0, error_code, message)
                outcome.attempts.append(
                    {
                        "database_id": database.database_id,
                        "status": error_code,
                        "result_count": 0,
                        "requested_evidence": wanted,
                        "newly_found": [],
                        "error_message": message,
                        "pass_number": pass_number,
                    }
                )
                if progress:
                    await progress(
                        {
                            "event": "database_search_failed",
                            "database_id": database.database_id,
                            "error_message": message,
                            "pass_number": pass_number,
                        }
                    )
                # A single unavailable source must not abort the whole run.
                continue

            newly_found = await _absorb_matches(
                client, request_id, database.database_id, result, outcome, pass_number
            )
            _enrich_context(database.database_id, result, outcome)

            repository.complete_retrieval_attempt(
                attempt_id, len(result.get("matches", [])), "COMPLETED", None
            )
            outcome.attempts.append(
                {
                    "database_id": database.database_id,
                    "status": "COMPLETED",
                    "result_count": len(result.get("matches", [])),
                    "requested_evidence": wanted,
                    "newly_found": newly_found,
                    "error_message": None,
                    "pass_number": pass_number,
                }
            )

            if progress:
                await progress(
                    {
                        "event": "database_search_completed",
                        "database_id": database.database_id,
                        "result_count": len(result.get("matches", [])),
                        "newly_found": newly_found,
                        "pass_number": pass_number,
                    }
                )

        # --- generated evidence -------------------------------------------
        # Compiled from transaction rows across every source, using the same
        # search context, so the extract is scoped exactly like the documents.
        for code in wanted_generated:
            if code in outcome.found:
                continue
            if progress:
                await progress(
                    {
                        "event": "generating_evidence",
                        "evidence_code": code,
                        "pass_number": pass_number,
                    }
                )
            await _compile_tabular_evidence(
                client,
                request_id,
                spec,
                code,
                outcome,
                pass_number,
                scope=dict(scope_context if scope_context is not None else search_context),
                filters=dict(tabular_filters or {}),
            )

    outcome.missing = [code for code in required_evidence if code not in outcome.found]
    return outcome


async def _compile_tabular_evidence(
    client,
    request_id: str,
    spec,
    code: str,
    outcome: RetrievalOutcome,
    pass_number: int,
    scope: dict[str, Any],
    filters: dict[str, Any],
) -> None:
    """Build a spreadsheet of the row-level data behind this request.

    Rows are gathered from every configured source through MCP, then written
    as a single workbook into staging. From there the item is indistinguishable
    from a retrieved document: it validates, stages and packages the same way.
    """
    databases = enabled_databases()
    names = {database.database_id: database.name for database in databases}

    rows: list[dict[str, Any]] = []
    for database in databases:
        attempt_id = repository.start_retrieval_attempt(
            request_id=request_id,
            database_id=database.database_id,
            search_parameters={**scope, **filters},
            requested_evidence=[code],
            pass_number=pass_number,
        )
        result = await client.fetch_transactions(database.database_id, scope, filters)
        if result.get("status") != "SUCCESS":
            message = result.get("error_message") or "Transaction fetch failed."
            outcome.errors.append(f"{database.database_id}: {message}")
            repository.complete_retrieval_attempt(
                attempt_id, 0, result.get("error_code") or "ERROR", message
            )
            continue

        found_rows = result.get("rows", [])
        rows.extend(found_rows)
        repository.complete_retrieval_attempt(attempt_id, len(found_rows), "COMPLETED", None)

    if not rows:
        # Nothing to compile: leave the item missing so validation reports it.
        logger.info("No transaction rows matched for %s", code)
        return

    label = spec.label_for(code) if spec else code
    identifier = _tabular_identifier({**scope, **filters})
    filename = staging.staged_filename(code, identifier, ".xlsx")

    built = tabular.build_transaction_workbook(
        request_id,
        label=label,
        filename=filename,
        rows=rows,
        search_parameters={**scope, **filters},
        database_names=names,
        parameter_labels=spec.parameter_labels if spec else {},
    )

    metadata = {
        **{key: scope.get(key) for key in ("period", "sob", "nac_code")},
        "nac_code": scope.get("nac_range") or scope.get("nac_code"),
        "generated": "tabular",
        "applied_filters": {k: v for k, v in filters.items() if v not in (None, "")},
        "row_count": built["row_count"],
        "total_amount": built["total_amount"],
        "currency": built["currency"],
        "contributing_databases": built["contributing_databases"],
        "matched_on": sorted(scope),
    }

    evidence_id = repository.add_retrieved_evidence(
        request_id,
        document_id=f"GEN-{code}",
        document_type=code,
        identifier=identifier,
        # Not a document from one system: it is derived from several.
        source_database_id=GENERATED_SOURCE_ID,
        source_file_path=None,
        staged_file_path=built["staged_file_path"],
        match_status="FOUND",
        metadata=metadata,
        pass_number=pass_number,
    )

    outcome.found[code] = {
        "evidence_id": evidence_id,
        "document_id": f"GEN-{code}",
        "identifier": identifier,
        "source_database_id": GENERATED_SOURCE_ID,
        "staged_file_path": built["staged_file_path"],
        "matched_on": sorted(scope),
        "pass_number": pass_number,
        "row_count": built["row_count"],
    }
    logger.info(
        "Compiled %s: %d rows from %s",
        code,
        built["row_count"],
        ", ".join(built["contributing_databases"]),
    )


def _tabular_identifier(context: dict[str, Any]) -> str:
    """A short, stable identifier describing the extract's scope."""
    parts: list[str] = []
    period = context.get("period")
    if period:
        pieces = str(period).replace(",", " ").split()
        parts.append("".join(pieces[-2:]) if len(pieces) >= 2 else str(period))
    if context.get("sob"):
        parts.append(f"SOB{context['sob']}")
    nac = context.get("nac_range") or context.get("nac_code")
    if nac:
        parts.append(f"NAC{nac}")
    if context.get("report_type"):
        parts.append(str(context["report_type"]))
    return "-".join(parts) if parts else "EXTRACT"


async def _absorb_matches(
    client,
    request_id: str,
    database_id: str,
    result: dict[str, Any],
    outcome: RetrievalOutcome,
    pass_number: int,
) -> list[str]:
    """Stage and record each new match. Returns the evidence codes gained."""
    newly_found: list[str] = []

    for match in result.get("matches", []):
        document_type = match.get("document_type")
        if not document_type or document_type in outcome.found:
            continue

        retrieved = await client.retrieve_document(database_id, match["document_id"])
        staged = staging.stage_document(
            request_id,
            document_id=match["document_id"],
            document_type=document_type,
            identifier=match.get("identifier"),
            source_absolute_path=retrieved.get("absolute_path"),
            source_relative_path=retrieved.get("file_path") or match.get("file_path"),
            source_database_id=database_id,
            metadata=match.get("metadata") or {},
            matched_on=match.get("matched_on", []),
        )

        matched_on = match.get("matched_on", [])
        evidence_id = repository.add_retrieved_evidence(
            request_id,
            document_id=match["document_id"],
            document_type=document_type,
            identifier=match.get("identifier"),
            source_database_id=database_id,
            source_file_path=retrieved.get("file_path") or match.get("file_path"),
            staged_file_path=staged["staged_file_path"],
            match_status="FOUND",
            metadata={
                **{key: match.get(key) for key in _EVIDENCE_FIELDS},
                "title": (match.get("metadata") or {}).get("title"),
                "content_summary": match.get("content_summary"),
                "source_metadata": match.get("metadata") or {},
                "matched_on": matched_on,
                "staging_error": staged["error"],
            },
            pass_number=pass_number,
        )

        outcome.found[document_type] = {
            "evidence_id": evidence_id,
            "document_id": match["document_id"],
            "identifier": match.get("identifier"),
            "source_database_id": database_id,
            "staged_file_path": staged["staged_file_path"],
            "matched_on": matched_on,
            "pass_number": pass_number,
        }
        newly_found.append(document_type)

        # If this document was reachable only via an identifier learned from
        # another source, remember which source that was. It is what lets the
        # retry summary explain itself truthfully.
        for key in matched_on:
            origin = outcome.identifier_origin.get(key)
            if origin:
                outcome.unlocked_by[document_type] = origin
                break

    return newly_found


def _enrich_context(
    database_id: str, result: dict[str, Any], outcome: RetrievalOutcome
) -> None:
    """Fold identifiers discovered here into the context for later sources."""
    for key, value in (result.get("discovered_identifiers") or {}).items():
        if outcome.context.get(key) == value:
            continue
        outcome.context[key] = value
        # First source to reveal a key owns it.
        outcome.identifier_origin.setdefault(key, database_id)

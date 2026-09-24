"""Retrieval Agent: executes the retrieval plan through MCP only.

Keys come from the Evidence Source Registry. A key value is taken from a previously retrieved record only when the
registry documents that dependency ("PO Number [from INVOICE]") — no undocumented chains. Also handles alternative /
corroborating sources (Source Usage rule), identifier mismatches and bounded retries on source failures.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from observability import get_observability

from app.core.config import get_settings
from app.core.models import RetrievalPlan
from app.mcp.connectors import ConnectorResult
from app.mcp.gateway import McpGateway

log = logging.getLogger(__name__)


@dataclass
class RawEvidence:
    """Structured output of the Retrieval Agent for one required evidence type."""
    evidence_type: str
    found: bool
    step: RetrievalPlan | None = None
    result: ConnectorResult | None = None
    keys_used: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    reason: str | None = None
    source_error: bool = False
    notes: list[str] = field(default_factory=list)
    corroboration: list[dict[str, Any]] = field(default_factory=list)
    planned_source: str | None = None


def key_value(step: RetrievalPlan, param: str, context: dict[str, Any], derived: dict[tuple[str, str], Any]):
    """Request value, else a value derived from evidence — only if this step's registry row documents it."""
    if context.get(param) not in (None, ""):
        return context[param]
    source_type = step.derived.get(param)
    return derived.get((source_type, param)) if source_type else None


def resolve_keys(step: RetrievalPlan, context: dict[str, Any],
                 derived: dict[tuple[str, str], Any] | None = None) -> dict[str, Any] | None:
    """One value per key group (first alternative available), or None if any group is unsatisfied."""
    keys = {}
    for group in step.key_groups or [[k] for k in step.key_names]:
        for p in group:
            v = key_value(step, p, context, derived or {})
            if v not in (None, ""):
                keys[p] = v
                break
        else:
            return None
    return keys


def derivable_by_type(plan: list[RetrievalPlan]) -> dict[str, set[str]]:
    """Evidence type -> params that the registry says may be taken from its retrieved record."""
    out: dict[str, set[str]] = {}
    for step in plan:
        for param, source_type in step.derived.items():
            out.setdefault(source_type, set()).add(param)
    return out


def _label(param: str) -> str:
    return param.replace("_", " ").title().replace("Po ", "PO ").replace("Id", "ID")


class RetrievalAgent:
    def __init__(self, gateway: McpGateway):
        self.gateway = gateway
        self.max_attempts = max(1, get_settings().retrieval_max_attempts)

    def _call(self, step: RetrievalPlan, keys: dict[str, Any]) -> tuple[ConnectorResult, int]:
        tool = McpGateway.tool_name(step.source_system)
        args = {"operation": step.endpoint, "keys": keys, "include_documents": True, "request_id": step.request_id}
        attempts = 1
        res = self.gateway.call_tool(tool, args)
        while not res.ok and res.source_error and attempts < self.max_attempts:
            attempts += 1
            with get_observability().retry(component="retrieval_agent", operation=tool, retry_number=attempts - 1,
                                           reason="source_error", previous_error_type=res.error_kind,
                                           evidence_type=step.evidence_type, source_system=step.source_system) as retry:
                res = self.gateway.call_tool(tool, args)
                retry.set_outcome("success" if res.ok else ("source_error" if res.source_error else "not_found"))
        return res, attempts

    def execute(self, plan: list[RetrievalPlan], parameters: dict[str, Any]) -> tuple[list[RawEvidence], list[str]]:
        context = {k: v for k, v in parameters.items() if v not in (None, "")}
        user_supplied = dict(context)
        derived: dict[tuple[str, str], Any] = {}  # (source evidence type, param) -> value
        derivable = derivable_by_type(plan)
        warnings: list[str] = []
        by_type: dict[str, list[RetrievalPlan]] = {}
        for step in plan:
            by_type.setdefault(step.evidence_type, []).append(step)

        outcomes: dict[str, RawEvidence] = {}
        pending = list(by_type)
        progress = True
        while pending and progress:
            progress = False
            for et in list(pending):
                steps = by_type[et]
                candidates = [s for s in steps if s.role == "primary"] + [s for s in steps if s.role == "alternative"]
                if not any(resolve_keys(s, context, derived) for s in candidates):
                    continue  # keys not yet known; a documented dependency may still provide them
                pending.remove(et)
                progress = True
                outcomes[et] = self._retrieve_type(et, candidates, [s for s in steps if s.role == "corroborating"],
                                                   context, derived, user_supplied, warnings, derivable)

        for et in pending:  # keys never became available
            steps = by_type[et]
            src = next((s.source_system for s in steps if s.role == "primary"), steps[0].source_system if steps else None)
            step = next((s for s in steps if s.role == "primary"), steps[0] if steps else None)
            missing = [" or ".join(_label(p) for p in g) for g in (step.key_groups if step else [])
                       if not any(key_value(step, p, context, derived) for p in g)]
            dep = next((f" (expected from {s.derived[p]})" for s in steps for g in s.key_groups for p in g
                        if p in s.derived and not key_value(s, p, context, derived)), "")
            outcomes[et] = RawEvidence(et, False, reason=f"Missing in {src} · required key {', '.join(missing)} not available{dep}",
                                       planned_source=src)
        return [outcomes[et] for et in by_type if et in outcomes], warnings

    def _retrieve_type(self, et, candidates, corroborating, context, derived, user_supplied, warnings,
                       derivable) -> RawEvidence:
        last: RawEvidence | None = None
        primary_src = candidates[0].source_system if candidates else None
        for step in candidates:
            keys = resolve_keys(step, context, derived)
            if keys is None:
                continue
            res, attempts = self._call(step, keys)
            if res.ok and res.records:
                raw = RawEvidence(et, True, step=step, result=res, keys_used=keys, attempts=attempts, planned_source=primary_src)
                if step.role == "alternative":
                    raw.notes.append(f"Retrieved from alternative source {step.source_system} ({last.reason if last else 'primary unavailable'})")
                self._harvest(res, et, derived, user_supplied, raw, warnings, derivable.get(et, set()))
                for c in corroborating:
                    ckeys = resolve_keys(c, context, derived)
                    if ckeys:
                        cres, _ = self._call(c, ckeys)
                        raw.corroboration.append({
                            "source_system": c.source_system, "matched": bool(cres.ok and cres.records),
                            "reference": str(cres.records[0].get(cres.reference_field)) if cres.ok and cres.records else None,
                        })
                return raw
            key_desc = " · ".join(f"{v}" for v in keys.values())
            if res.source_error:
                reason = f"{step.source_system} unavailable after {attempts} attempt(s) · retry possible"
            else:
                reason = f"Missing in {step.source_system} · no record for {key_desc}"
            last = RawEvidence(et, False, step=step, result=res, keys_used=keys, attempts=attempts,
                               reason=reason, source_error=res.source_error, planned_source=primary_src)
        return last or RawEvidence(et, False, reason="No applicable source mapping", planned_source=primary_src)

    @staticmethod
    def _harvest(res: ConnectorResult, evidence_type: str, derived, user_supplied, raw: RawEvidence,
                 warnings: list[str], allowed: set[str]) -> None:
        """Record only the identifiers the registry declares as derivable from this evidence type."""
        record = res.records[0]
        for key in sorted(allowed):
            val = record.get(key)
            if val in (None, ""):
                continue
            val = str(val)
            if key in user_supplied and str(user_supplied[key]) != val:
                msg = (f"Identifier mismatch: {res.source_system} record references {key.replace('_', ' ')} {val}, "
                       f"request specified {user_supplied[key]}")
                raw.notes.append(msg)
                warnings.append(msg)
                continue
            derived.setdefault((evidence_type, key), val)

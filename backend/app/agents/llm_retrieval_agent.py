"""Agentic Retrieval Agent: an LLM drives retrieval through MCP tool calls.

The model decides the order of calls, derives dependent keys from earlier results (e.g. the PO number
printed on an invoice) and chooses when to fall back to alternative sources. Guardrails keep it inside
the approved retrieval plan:

  * only (evidence type, source system) pairs from the plan can be called — no invented sources;
  * key names must match the registry's Search / Retrieval Keys for that mapping (one per key group);
  * key values must come from the request or from a documented dependency ("[from X]") — no invented identifiers;
  * alternatives only after the primary source returned nothing; corroborating only after a primary hit;
  * a hard step budget.

Anything the agent leaves untried is completed by the deterministic executor, and any LLM failure
falls back to the deterministic executor entirely — retrieval never depends on the LLM being up.
"""
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from observability import get_observability
from pydantic import BaseModel, Field

from app.agents.llm import get_chat_model, llm_enabled, llm_identity
from app.agents.retrieval_agent import RawEvidence, RetrievalAgent, derivable_by_type, key_value
from app.core.config import get_settings
from app.core.models import RetrievalPlan

log = logging.getLogger(__name__)


class RetrieveEvidence(BaseModel):
    """Call the MCP connector for one (evidence type, source system) pair from the retrieval plan."""
    evidence_type: str = Field(description="Evidence type code from the plan, e.g. INVOICE")
    source_system: str = Field(description="Source system from the plan, e.g. GROSS")
    keys: dict[str, str] = Field(description="Search keys: exactly one key name from each key group of that plan step")


SYSTEM_PROMPT = """You are the Retrieval Agent of an audit evidence platform. You retrieve evidence ONLY by calling the
RetrieveEvidence tool, which reaches enterprise source systems through MCP.

Rules:
1. Only call (evidence_type, source_system) pairs listed in the retrieval plan. Provide exactly one key from each
   key group (key_groups lists alternatives per group).
2. Key values must come from the known identifiers, or — only where the plan lists derived_from — from the identifiers
   returned by that evidence type's tool result. Never guess.
3. For each evidence type call its primary source first. Call an alternative source only if the primary returned no record.
   Call corroborating sources only after the primary returned a record.
4. When a key is missing but the plan says it is derived_from another evidence type, retrieve that evidence first.
5. Do not repeat a call that already returned found=false unless the result says retryable=true.
6. When every evidence type is retrieved or has no remaining options, reply with a one-paragraph summary and no tool call."""


COMPONENT = "retrieval_agent"
OPERATION = "agentic_retrieval"
FALLBACK = "deterministic_executor"


class AgenticRetrievalAgent(RetrievalAgent):
    def execute(self, plan: list[RetrievalPlan], parameters: dict[str, Any]) -> tuple[list[RawEvidence], list[str]]:
        obs = get_observability()
        with obs.agent(COMPONENT, operation=OPERATION) as agent:
            agent.annotate(plan_steps=len(plan))
            if not plan:
                agent.annotate(llm_used=False, mode="empty_plan")
                return super().execute(plan, parameters)
            if not llm_enabled() or not get_settings().llm_agentic_retrieval:
                reason = "llm_disabled" if not llm_enabled() else "agentic_retrieval_disabled"
                return self._fallback(plan, parameters, reason, agent)
            try:
                result = self._agentic(plan, parameters, agent)
                agent.annotate(llm_used=True, mode="agentic", found=sum(r.found for r in result[0]))
                return result
            except Exception as exc:
                log.warning("agentic retrieval failed; using deterministic executor", exc_info=True)
                return self._fallback(plan, parameters, "llm_error", agent, exc)

    def _fallback(self, plan, parameters, reason: str, agent, error: BaseException | None = None):
        obs = get_observability()
        obs.log_fallback_started(component=COMPONENT, operation=OPERATION, fallback_type=FALLBACK, reason=reason,
                                 error=error)
        result = super().execute(plan, parameters)
        obs.log_fallback_completed(component=COMPONENT, operation=OPERATION, fallback_type=FALLBACK, reason=reason,
                                   found=sum(r.found for r in result[0]), evidence_types=len(result[0]))
        agent.annotate(llm_used=False, mode=FALLBACK, fallback_reason=reason, found=sum(r.found for r in result[0]))
        return result

    # ------------------------------------------------------------------------------------------
    def _agentic(self, plan: list[RetrievalPlan], parameters: dict[str, Any], agent):
        context = {k: str(v) for k, v in parameters.items() if v not in (None, "")}
        user_supplied = dict(context)
        derived: dict[tuple[str, str], Any] = {}
        derivable = derivable_by_type(plan)
        warnings: list[str] = []
        found: dict[str, RawEvidence] = {}
        failed: dict[str, RawEvidence] = {}
        tried: set[tuple[str, str]] = set()
        types = list(dict.fromkeys(s.evidence_type for s in plan))

        def run_tool(args: dict[str, Any]) -> dict[str, Any]:
            et = str(args.get("evidence_type", "")).upper()
            src = str(args.get("source_system", "")).upper()
            keys = {str(k): str(v) for k, v in (args.get("keys") or {}).items()}
            step = next((s for s in plan if s.evidence_type == et and s.source_system == src), None)
            if step is None:
                return {"error": f"{et} from {src} is not in the retrieval plan."}
            groups = step.key_groups or [[k] for k in step.key_names]
            if len(keys) != len(groups) or not all(sum(k in g for k in keys) == 1 for g in groups):
                return {"error": f"Provide exactly one key from each group for {et}/{src}: {groups}."}
            unknown = [v for k, v in keys.items() if str(key_value(step, k, context, derived)) != v]
            if unknown:
                return {"error": f"Identifiers {unknown} are not known for this step. Use values from the request, "
                                 "or from the evidence type listed in derived_from."}
            if step.role == "alternative":
                primary_tried = any(s.role == "primary" and (s.evidence_type, s.source_system) in tried
                                    for s in plan if s.evidence_type == et)
                if et in found or not primary_tried:
                    return {"error": "Alternative sources may only be used after the primary source returned no record."}
            if step.role == "corroborating" and et not in found:
                return {"error": "Corroborating sources may only be called after the primary evidence was found."}
            if (et, src) in tried and step.role != "corroborating" and not (et in failed and failed[et].source_error):
                return {"error": "Already attempted; it did not return a record and is not retryable."}
            tried.add((et, src))

            res, attempts = self._call(step, keys)
            if step.role == "corroborating":
                matched = bool(res.ok and res.records)
                found[et].corroboration.append({
                    "source_system": src, "matched": matched,
                    "reference": str(res.records[0].get(res.reference_field)) if matched else None,
                })
                return {"found": matched}
            if res.ok and res.records:
                primary = next((s.source_system for s in plan if s.evidence_type == et and s.role == "primary"), src)
                raw = RawEvidence(et, True, step=step, result=res, keys_used=keys, attempts=attempts, planned_source=primary)
                if step.role == "alternative" and et in failed:
                    raw.notes.append(f"Retrieved from alternative source {src} ({failed[et].reason})")
                self._harvest(res, et, derived, user_supplied, raw, warnings, derivable.get(et, set()))
                found[et] = raw
                failed.pop(et, None)
                record = res.records[0]
                return {"found": True, "reference": str(record.get(res.reference_field)),
                        "identifiers": {k: str(record[k]) for k in sorted(derivable.get(et, set()))
                                        if record.get(k) not in (None, "")}}
            key_desc = " · ".join(keys.values())
            reason = (f"{src} unavailable after {attempts} attempt(s) · retry possible" if res.source_error
                      else f"Missing in {src} · no record for {key_desc}")
            failed[et] = RawEvidence(et, False, step=step, result=res, keys_used=keys, attempts=attempts,
                                     reason=reason, source_error=res.source_error, planned_source=src)
            return {"found": False, "retryable": res.source_error, "reason": reason}

        plan_view = [{"evidence_type": s.evidence_type, "source_system": s.source_system, "role": s.role,
                      "key_groups": s.key_groups, "derived_from": s.derived} for s in plan]
        messages: list = [
            SystemMessage(SYSTEM_PROMPT),
            HumanMessage(json.dumps({"retrieval_plan": plan_view, "known_identifiers": context}, indent=1)),
        ]
        obs = get_observability()
        provider, model_name = llm_identity()
        model = get_chat_model().bind_tools([RetrieveEvidence])
        budget = 3 * len(plan) + 4
        steps = 0
        for step_no in range(1, budget + 1):
            with obs.llm_call(component=COMPONENT, operation="evidence_tool_selection", provider=provider,
                              model=model_name) as llm_call:
                llm_call.set_messages(messages)
                ai: AIMessage = model.invoke(messages)
                llm_call.set_response(ai)
                llm_call.annotate(step=step_no)
            steps = step_no
            messages.append(ai)
            if not ai.tool_calls:
                log.info("retrieval agent finished: %s", (ai.content or "")[:300])
                break
            with obs.triggered_by_llm(llm_call.run_id):  # MCP tool spans record the LLM run that requested them
                for call in ai.tool_calls:
                    result = run_tool(call.get("args", {}))
                    messages.append(ToolMessage(json.dumps(result), tool_call_id=call["id"]))
        agent.annotate(llm_steps=steps, step_budget=budget)

        # Deterministic completion for evidence types the agent never attempted.
        untried = [et for et in types if et not in found and et not in failed]
        agent.annotate(completed_deterministically=len(untried))
        if untried:
            seeded = dict(context)  # carry documented derived keys into the deterministic completion
            for s in plan:
                if s.evidence_type in untried:
                    for p, src in s.derived.items():
                        if (src, p) in derived:
                            seeded.setdefault(p, derived[(src, p)])
            rest, more = RetrievalAgent.execute(self, [s for s in plan if s.evidence_type in untried], seeded)
            warnings += more
            for raw in rest:
                (found if raw.found else failed)[raw.evidence_type] = raw
        return [found.get(et) or failed[et] for et in types], warnings

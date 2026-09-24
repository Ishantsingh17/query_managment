"""Usage extraction, optional token estimation and optional cost estimation.

* `extract_usage` reads provider-reported usage from common response shapes (LangChain `AIMessage.usage_metadata`,
  LangChain `LLMResult.llm_output`, OpenAI / Anthropic SDK responses, plain dicts). It never invents numbers:
  if nothing is reported it returns None.
* `estimate_usage` is a clearly-labelled heuristic (`usage_source="estimated"`), used only when
  `OBSERVABILITY_TOKEN_ESTIMATION_ENABLED=true`.
* `estimate_cost` uses only operator-supplied pricing; no prices are built into this module.
"""
from collections.abc import Mapping
from typing import Any

from observability.enums import UsageSource
from observability.models import TokenUsage

ESTIMATION_METHOD = "chars_div_4"  # ~4 characters per token for English text; documented, deliberately simple


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _from_usage_dict(u: Any) -> TokenUsage | None:
    """Normalize LangChain usage_metadata / OpenAI usage / Anthropic usage / token_usage dicts."""
    if u is None:
        return None
    inp = _int(_get(u, "input_tokens"))
    if inp is None:
        inp = _int(_get(u, "prompt_tokens"))
    out = _int(_get(u, "output_tokens"))
    if out is None:
        out = _int(_get(u, "completion_tokens"))
    total = _int(_get(u, "total_tokens"))
    in_details = _get(u, "input_token_details") or _get(u, "prompt_tokens_details")
    out_details = _get(u, "output_token_details") or _get(u, "completion_tokens_details")
    cached = _int(_get(in_details, "cache_read")) or _int(_get(in_details, "cached_tokens")) \
        or _int(_get(u, "cache_read_input_tokens"))
    reasoning = _int(_get(out_details, "reasoning")) or _int(_get(out_details, "reasoning_tokens"))
    if inp is None and out is None and total is None:
        return None
    details: dict[str, Any] = {}
    for name, d in (("input_token_details", in_details), ("output_token_details", out_details)):
        if isinstance(d, Mapping):
            details[name] = {k: v for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        elif d is not None and hasattr(d, "model_dump"):
            details[name] = {k: v for k, v in d.model_dump().items() if isinstance(v, (int, float)) and v is not None}
    cache_creation = _int(_get(u, "cache_creation_input_tokens"))
    if cache_creation is not None:
        details["cache_creation_input_tokens"] = cache_creation
    return TokenUsage(input_tokens=inp, output_tokens=out, total_tokens=total, cached_tokens=cached,
                      reasoning_tokens=reasoning, source=UsageSource.PROVIDER,
                      details={k: v for k, v in details.items() if v not in ({}, None)})


def extract_usage(response: Any) -> TokenUsage | None:
    """Provider-reported usage from a model response, or None when the provider reported nothing."""
    if response is None:
        return None
    try:
        # LangChain AIMessage / AIMessageChunk
        usage = _from_usage_dict(_get(response, "usage_metadata"))
        if usage:
            return usage
        # LangChain LLMResult (callbacks): generations[i][j].message.usage_metadata, else llm_output.token_usage
        generations = _get(response, "generations")
        if isinstance(generations, list) and generations:
            total: TokenUsage | None = None
            for batch in generations:
                for gen in batch if isinstance(batch, list) else [batch]:
                    u = _from_usage_dict(_get(_get(gen, "message"), "usage_metadata"))
                    if u:
                        total = u if total is None else total + u
            if total:
                return total
            llm_output = _get(response, "llm_output") or {}
            return _from_usage_dict(_get(llm_output, "token_usage") or _get(llm_output, "usage"))
        # LangChain response_metadata.token_usage (some providers)
        meta = _get(response, "response_metadata")
        usage = _from_usage_dict(_get(meta, "token_usage") or _get(meta, "usage"))
        if usage:
            return usage
        # OpenAI / Anthropic / Groq SDK responses and plain dicts: `.usage`
        return _from_usage_dict(_get(response, "usage"))
    except Exception:  # noqa: BLE001
        return None


def extract_response_model(response: Any) -> str | None:
    """Model name echoed back by the provider, when available."""
    try:
        meta = _get(response, "response_metadata") or {}
        return _get(meta, "model_name") or _get(meta, "model") or _get(response, "model") or None
    except Exception:  # noqa: BLE001
        return None


def _text_len(obj: Any) -> int:
    if obj is None:
        return 0
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, Mapping):
        if "content" in obj:  # a chat message: count its content, not its role
            return _text_len(obj["content"])
        return sum(_text_len(v) for v in obj.values())
    if isinstance(obj, tuple) and len(obj) == 2 and isinstance(obj[0], str):  # (role, content)
        return _text_len(obj[1])
    if isinstance(obj, (list, tuple)):
        return sum(_text_len(v) for v in obj)
    content = getattr(obj, "content", None)
    if content is not None:
        return _text_len(content)
    return len(str(obj))


def estimate_usage(inputs: Any, outputs: Any) -> TokenUsage:
    """Heuristic estimate. Always labelled `estimated` so it is never confused with provider numbers."""
    inp = max(1, round(_text_len(inputs) / 4)) if inputs is not None else None
    out = max(1, round(_text_len(outputs) / 4)) if outputs is not None else None
    return TokenUsage(input_tokens=inp, output_tokens=out, source=UsageSource.ESTIMATED,
                      details={"estimation_method": ESTIMATION_METHOD})


def estimate_cost(usage: TokenUsage | None, model: str | None, settings: Any) -> tuple[float, str, str] | None:
    """(estimated_cost, currency, pricing_source) from configured pricing only; None when not configured."""
    if usage is None or not getattr(settings, "cost_tracking_enabled", False):
        return None
    prices = (settings.model_pricing or {}).get(model or "", {}) if model else {}
    in_price = prices.get("input_cost_per_1k_tokens", settings.input_cost_per_1k_tokens)
    out_price = prices.get("output_cost_per_1k_tokens", settings.output_cost_per_1k_tokens)
    if in_price is None and out_price is None:
        return None
    if usage.input_tokens is None and usage.output_tokens is None:
        return None
    cost = (usage.input_tokens or 0) / 1000 * (in_price or 0) + (usage.output_tokens or 0) / 1000 * (out_price or 0)
    source = "configuration:model" if prices else "configuration:default"
    return round(cost, 8), settings.cost_currency, source

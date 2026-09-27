"""LLM provider abstraction (configuration-driven, TRD §2).

`groq`      — ChatGroq with GROQ_API_KEY (default model openai/gpt-oss-120b).
`langchain` — any provider supported by LangChain's init_chat_model, e.g. AEP_LLM_MODEL="openai:gpt-4.1".

Outputs are always validated against controlled values (the Requirement Catalog). There is no rules-based
fallback: any LLM failure (rate limit / API limit, auth, timeout, invalid output) raises `LlmUnavailableError`,
which the API returns to the user as a clear message. The call is attempted even without credentials, so a real
provider/auth failure happens and is traced (observability `llm_call` span -> local JSONL file, and LangSmith when
tracing is on) rather than assumed locally. Every LLM call is reported through the generic observability API.
"""
import logging
from typing import Literal

from observability import get_observability
from pydantic import BaseModel, Field, create_model

from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)

_model_override = None  # tests inject a fake chat model here


class LlmUnavailableError(AppError):
    """The LLM could not produce a usable answer; the request cannot be understood without it."""
    status_code = 503
    code = "llm_unavailable"


def _describe_failure(exc: Exception) -> str:
    name = type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429 or "RateLimit" in name:
        return "The AI service's usage limit was reached. Please wait a minute and try again."
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return "The AI service rejected the credentials. Check the LLM API key in backend/.env."
    if "Timeout" in name:
        return "The AI service did not respond in time. Please try again."
    if "ValidationError" in name or "OutputParser" in name:
        return "The AI service returned an answer that could not be used. Please try again or rephrase the request."
    return f"The AI service is unavailable right now ({name}). Please try again."


def llm_enabled() -> bool:
    """True whenever a real LLM provider is configured. Credentials are not checked here: the call is still
    attempted without them so a genuine provider/auth failure is made and traced, rather than assumed locally."""
    if _model_override is not None:
        return True
    return get_settings().llm_provider in ("groq", "langchain")


def set_chat_model(model) -> None:
    global _model_override, _cached
    _model_override = model
    _cached = None


_cached = None

QU_COMPONENT = "query_understanding_agent"
QU_OPERATION = "structured_query_generation"


def llm_identity() -> tuple[str, str]:
    """(provider, model) of the configured chat model, for telemetry only."""
    s = get_settings()
    if _model_override is not None:
        m = _model_override
        return "custom", str(getattr(m, "model_name", None) or getattr(m, "model", None) or type(m).__name__)
    if s.llm_provider == "langchain":
        provider, _, name = s.llm_model.partition(":")
        return (provider, name) if name else ("langchain", s.llm_model)
    return s.llm_provider, s.llm_model


def get_chat_model():
    """Base chat model (supports .with_structured_output and .bind_tools)."""
    global _cached
    if _model_override is not None:
        return _model_override
    if _cached is None:
        s = get_settings()
        if s.llm_provider == "groq":
            from langchain_groq import ChatGroq
            _cached = ChatGroq(model=s.llm_model, api_key=s.groq_api_key, temperature=0,
                               timeout=s.llm_timeout_seconds, max_retries=2)
        else:
            from langchain.chat_models import init_chat_model
            _cached = init_chat_model(s.llm_model, temperature=0, timeout=s.llm_timeout_seconds)
    return _cached


class LlmQueryExtraction(BaseModel):
    """Structured interpretation of an audit evidence request."""
    query_type: str | None = Field(None, description="Best matching supported query type code, or null if unclear")
    classification_rationale: str = Field("", description="One sentence explaining the query type choice")
    ambiguous_between: list[str] = Field(default_factory=list,
                                         description="Only if the request fits two or more supported types equally well")
    payment_document_number: str | None = Field(None, description="10-digit payment document number if present")
    invoice_number: str | None = Field(None, description="Invoice number (e.g. INV-2026-08455) if present")
    po_number: str | None = Field(None, description="Purchase order number if present")
    vendor_id: str | None = Field(None, description="Vendor ID if present")
    employee_id: str | None = Field(None, description="Employee ID (e.g. E-20413) if present")
    fiscal_year: str | None = Field(None, description="Fiscal year as 4 digits, only if explicitly stated (FY2026 -> 2026)")
    period_start: str | None = Field(None, description="ISO date for start of the audit period if present")
    period_end: str | None = Field(None, description="ISO date for end of the audit period if present")


def _schema_for(supported: list[str]) -> type[BaseModel]:
    """Constrain query_type to the catalog's codes so the model cannot invent or combine types."""
    return create_model(
        "AuditQueryExtraction", __base__=LlmQueryExtraction,
        query_type=(Literal[tuple(supported)] | None, Field(None, description="One supported query type code, or null")),  # type: ignore[valid-type]
        ambiguous_between=(list[Literal[tuple(supported)]], Field(  # type: ignore[valid-type]
            default_factory=list, description="Only if the request fits two or more supported types equally well")),
    )


SYSTEM_PROMPT = (
    "You are the Query Understanding and Query Type Classification agent of an internal audit evidence platform. "
    "Extract business identifiers that literally appear in the auditor's request, and choose exactly ONE query type "
    "from the supported list (or null when none fits). If it fits several types equally, list them in ambiguous_between. "
    "Never invent identifiers, evidence requirements or source systems."
)


def llm_extract(text: str, supported: dict[str, str] | None = None) -> LlmQueryExtraction:
    """`supported` maps query type code -> description of what it covers (from the Requirement Catalog).
    Raises LlmUnavailableError when no LLM is configured or the call fails."""
    if not llm_enabled():
        raise LlmUnavailableError("No LLM provider is configured. Set AEP_LLM_PROVIDER to groq or langchain "
                                  "in backend/.env.", code="llm_not_configured")
    obs = get_observability()
    supported = supported or {}
    provider, model_name = llm_identity()
    try:
        catalog = "\n".join(f"- {code}: {desc}" for code, desc in supported.items()) or "- (none)"
        schema = _schema_for(list(supported)) if supported else LlmQueryExtraction
        messages = [("system", f"{SYSTEM_PROMPT}\n\nSupported query types:\n{catalog}"), ("human", text)]
        with obs.llm_call(component=QU_COMPONENT, operation=QU_OPERATION, provider=provider, model=model_name) as call:
            call.set_messages(messages)
            model = get_chat_model().with_structured_output(schema)
            out = model.invoke(messages)
            if isinstance(out, dict):
                out = schema(**out)
            if out.query_type and supported and out.query_type not in supported:
                out.query_type = None
            result = LlmQueryExtraction(**out.model_dump())
            call.set_output(result.model_dump())
            call.set_parsed(True)
        return result
    except Exception as exc:  # provider/network/rate-limit/validation failure -> surfaced to the user
        # The failing obs.llm_call span above already recorded the real error (type, message, provider,
        # model) to every active sink — the local JSONL file and LangSmith when tracing is on.
        log.error("LLM query understanding failed", exc_info=True)
        raise LlmUnavailableError(_describe_failure(exc)) from exc

"""Query Understanding Agent.

Converts an auditor's natural-language request into schema-valid structured
JSON. Groq is the primary path; a deterministic parser is the fallback so the
POC stays demonstrable when no key is configured or the model misbehaves.

The agent classifies and extracts only. It never decides what evidence a use
case requires - that comes from the Requirement Catalog - and it never
invents a parameter value that was not in the request.
"""

from __future__ import annotations

import logging

from app.agents import rule_parser
from app.catalog.loader import get_use_case, load_use_cases
from app.config import get_settings
from app.schemas import ParsedQuery, ParsedQueryEnvelope, SearchParameters

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Query Understanding Agent for an audit evidence \
retrieval system. Convert the auditor's request into structured JSON.

Classify the request into EXACTLY ONE of these use cases:

{catalog}

Disambiguating the overlapping requirements:
- The word "schedule" alone does not mean UC-02. If the request concerns TRADE \
PAYABLES, vendor balances, APTB, or balance confirmations, choose UC-03 even \
when it says "schedule" or "ageing". UC-02 is for account-level schedules \
driven by an account number.
- UC-03 covers requesting or preparing balance confirmations. UC-04 covers the \
ALTERNATE testing performed when a confirmation was not returned, and is \
identified by invoice-level document requests (invoice, PO, GRN, SES).

Rules you must follow:
1. Choose exactly one use_case_id from UC-01, UC-02, UC-03, UC-04, or UNSUPPORTED.
2. Use UNSUPPORTED when the request is not one of the four requirements above.
3. Extract ONLY values that literally appear in the request. Never guess, \
infer, or invent a value. If a parameter is absent, leave it null.
4. Do NOT decide which documents are required - that is configured elsewhere.
5. Do NOT invent database names, audit rules, or audit methodology.
6. Normalise formats: period as "August 2026" or "30 June 2026"; NAC ranges as \
"5000-5999"; invoice numbers uppercase as "INV-12345"; report_type as AP, AR or OTHERS.
7. Put the account number in "account" and the vendor name in "vendor_name".
8. confidence is your certainty from 0.0 to 1.0.
9. List anything genuinely unclear, or any mandatory input that is missing, in \
"ambiguities".
"""


def _catalog_text() -> str:
    lines = []
    for use_case_id, spec in load_use_cases().items():
        params = ", ".join(spec.required_parameters)
        lines.append(f"- {use_case_id} ({spec.name}): required inputs = {params}")
    return "\n".join(lines)


def _build_model():
    """Construct the Groq chat model, or None when unusable."""
    settings = get_settings()
    if not settings.groq_enabled:
        return None, "GROQ_API_KEY is not configured."
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover
        return None, f"langchain-groq is not installed: {exc}"

    try:
        model = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0,
            timeout=settings.groq_timeout_seconds,
            max_retries=1,
        )
    except Exception as exc:
        return None, f"Groq model could not be initialised: {exc}"
    return model, None


def _backfill_from_rules(parsed: ParsedQuery, raw_query: str) -> ParsedQuery:
    """Fill parameters the model left empty using the deterministic parser.

    Values like "SOB 101", "NAC 5000-5999" and the AP/AR report type are
    pure pattern matches, and the regex parser gets them every time while the
    model occasionally overlooks one. Without this, the same request can ask
    the auditor for a different set of inputs on different runs.

    Only empty fields are filled - whatever the model did extract always wins,
    and nothing is invented: a value must be present in the request text.
    """
    if not parsed.is_supported:
        return parsed

    from_rules = rule_parser.parse(raw_query)
    if from_rules.use_case_id != parsed.use_case_id:
        # A different classification means the rule parser read the request
        # differently; its parameters may not belong to this use case.
        return parsed

    supplied = parsed.search_parameters.provided()
    extra = {
        key: value
        for key, value in from_rules.search_parameters.provided().items()
        if key not in supplied
    }
    if not extra:
        return parsed

    merged = SearchParameters(**{**supplied, **extra})
    return parsed.model_copy(update={"search_parameters": merged})


def _normalise(parsed: ParsedQuery) -> ParsedQuery:
    """Backfill the requirement name from the catalog and tidy ambiguities."""
    if parsed.use_case_id == "UNSUPPORTED":
        return parsed.model_copy(update={"requirement": "", "confidence": parsed.confidence})

    spec = get_use_case(parsed.use_case_id)
    if spec is None:
        return parsed

    updates: dict = {"requirement": spec.name}

    # Flag mandatory inputs the model did not extract, so the UI can show them.
    supplied = parsed.search_parameters.provided()
    ambiguities = list(parsed.ambiguities or [])

    for key in spec.required_parameters:
        if key == "vendor_sample":
            present = bool(
                parsed.search_parameters.vendor_sample or parsed.search_parameters.vendor_name
            )
        else:
            present = key in supplied
        if present:
            continue

        label = spec.parameter_label(key)
        # The model often reports the same gap in its own words. Only add our
        # note when it has not already mentioned this parameter, otherwise the
        # UI lists every missing input twice.
        already_mentioned = any(
            key.lower() in existing.lower() or label.lower() in existing.lower()
            for existing in ambiguities
        )
        if not already_mentioned:
            ambiguities.append(f"{label} was not found in the request.")

    updates["ambiguities"] = ambiguities
    return parsed.model_copy(update=updates)


def understand(raw_query: str) -> ParsedQueryEnvelope:
    """Parse a request, preferring Groq and falling back deterministically."""
    settings = get_settings()
    model, unavailable = _build_model()

    if model is not None:
        try:
            structured = model.with_structured_output(ParsedQuery, include_raw=True)
            prompt = SYSTEM_PROMPT.format(catalog=_catalog_text())
            response = structured.invoke(
                [("system", prompt), ("human", raw_query.strip())]
            )

            parsing_error = response.get("parsing_error") if isinstance(response, dict) else None
            parsed = response.get("parsed") if isinstance(response, dict) else response

            if parsing_error or parsed is None:
                reason = f"Groq output did not satisfy the schema: {parsing_error}"
                logger.warning("Query understanding falling back to rules: %s", reason)
                return _fallback(raw_query, reason)

            return ParsedQueryEnvelope(
                parsed=_normalise(_backfill_from_rules(parsed, raw_query)),
                parse_source="GROQ",
                model=settings.groq_model,
            )
        except Exception as exc:
            # Never log the API key; only the failure class and message.
            reason = f"Groq request failed: {type(exc).__name__}: {exc}"
            logger.warning("Query understanding falling back to rules: %s", reason)
            return _fallback(raw_query, reason)

    return _fallback(raw_query, unavailable or "Groq is unavailable.")


def _fallback(raw_query: str, reason: str) -> ParsedQueryEnvelope:
    parsed = _normalise(rule_parser.parse(raw_query))
    return ParsedQueryEnvelope(
        parsed=parsed,
        parse_source="RULE_BASED",
        model=None,
        fallback_reason=reason,
    )

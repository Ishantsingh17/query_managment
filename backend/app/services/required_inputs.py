"""Mandatory-input checking.

The Requirement Catalog declares which inputs each use case cannot be searched
without. This module is the single place that decides whether a parsed request
has them, and how to ask for the ones it is missing.

Why this gate exists
--------------------
Search parameters are the keys used against the source systems. A use case's
mandatory inputs are the ones that make a search *selective*: period alone
identifies thousands of rows in a real ERP, so a cost drill request without
SOB, NAC range and report type would return whichever document happened to
come back first - confidently, and wrong. Refusing to search is the safe
answer; asking the auditor for the missing values is the useful one.
"""

from __future__ import annotations

from typing import Any

from app.catalog.loader import UseCaseSpec, get_use_case


def _is_supplied(key: str, parameters: dict[str, Any]) -> bool:
    """A vendor sample is satisfied by either a list or a single vendor."""
    if key == "vendor_sample":
        return bool(parameters.get("vendor_sample") or parameters.get("vendor_name"))
    value = parameters.get(key)
    return value not in (None, "", [])


def missing_required(spec: UseCaseSpec | None, parameters: dict[str, Any]) -> list[str]:
    """Mandatory input keys the request did not supply, in catalog order."""
    if spec is None:
        return []
    return [key for key in spec.required_parameters if not _is_supplied(key, parameters)]


def missing_for_use_case(use_case_id: str, parameters: dict[str, Any]) -> list[str]:
    return missing_required(get_use_case(use_case_id), parameters)


def describe(spec: UseCaseSpec | None, keys: list[str]) -> list[dict[str, str]]:
    """Missing keys with their auditor-facing labels, for the UI."""
    if spec is None:
        return [{"key": key, "label": key.replace("_", " ").title()} for key in keys]
    return [{"key": key, "label": spec.parameter_label(key)} for key in keys]


def _join(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def question_for(spec: UseCaseSpec | None, keys: list[str]) -> str | None:
    """The clarifying question to put to the auditor.

    Phrased as a question rather than an error, because the request was
    understood - it is only underspecified.
    """
    if not keys:
        return None
    labels = [item["label"] for item in describe(spec, keys)]
    requirement = spec.name if spec else "this request"
    return (
        f"To search for {requirement} evidence I also need "
        f"{_join(labels)}. Which {'value should' if len(labels) == 1 else 'values should'} I use?"
    )


def example_for(spec: UseCaseSpec | None, keys: list[str]) -> str | None:
    """A concrete example answer, so the auditor knows the expected shape."""
    samples = {
        "period": "August 2026",
        "sob": "SOB 101",
        "nac_range": "NAC 5000-5999",
        "report_type": "AP",
        "account": "account 4100",
        "vendor_name": "ABC Ltd",
        "invoice_number": "Invoice INV-12345",
        "vendor_sample": "ABC Ltd",
    }
    parts = [samples[key] for key in keys if key in samples]
    return ", ".join(parts) if parts else None

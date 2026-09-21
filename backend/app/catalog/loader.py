"""Requirement Catalog and Database Registry loader.

Configuration-first and deterministic: given a use case id, the required
evidence is resolved from YAML with no LLM involvement.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.config import get_settings

SUPPORTED_USE_CASE_IDS = ("UC-01", "UC-02", "UC-03", "UC-04")


class EvidenceRequirement(BaseModel):
    code: str
    label: str
    # Items needing human judgement can never be auto-satisfied.
    human_required: bool = False
    # Set to "tabular" for evidence that is COMPILED from row-level source
    # data rather than retrieved as an existing document. The Retrieval Agent
    # builds these instead of searching the documents table for a file.
    generated: str | None = None


class ValidationCheckSpec(BaseModel):
    code: str
    label: str
    parameter: str | None = None


class UseCaseSpec(BaseModel):
    use_case_id: str
    name: str
    short_name: str
    description: str
    icon: str = "file-search"
    required_parameters: list[str] = Field(default_factory=list)
    # Inputs that refine a search when supplied but are not mandatory. They
    # appear on the use-case card alongside the required ones, and their
    # absence never counts as an ambiguity.
    optional_parameters: list[str] = Field(default_factory=list)
    parameter_labels: dict[str, str] = Field(default_factory=dict)
    evidence: list[EvidenceRequirement] = Field(default_factory=list)
    validation_checks: list[ValidationCheckSpec] = Field(default_factory=list)

    @property
    def evidence_codes(self) -> list[str]:
        return [item.code for item in self.evidence]

    def label_for(self, code: str) -> str:
        for item in self.evidence:
            if item.code == code:
                return item.label
        return code.replace("_", " ").title()

    def requirement(self, code: str) -> EvidenceRequirement | None:
        for item in self.evidence:
            if item.code == code:
                return item
        return None

    @property
    def generated_codes(self) -> list[str]:
        """Evidence codes that are compiled, not searched for."""
        return [item.code for item in self.evidence if item.generated]

    def parameter_label(self, key: str) -> str:
        return self.parameter_labels.get(key, key.replace("_", " ").title())

    @property
    def all_parameters(self) -> list[str]:
        """Required inputs first, then optional ones, for display."""
        return [*self.required_parameters, *self.optional_parameters]


class DatabaseSpec(BaseModel):
    database_id: str
    name: str
    path: str
    enabled: bool = True
    search_order: int = 0

    def resolved_path(self, root: Path) -> Path:
        candidate = Path(self.path)
        return candidate if candidate.is_absolute() else root / candidate


def _read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=1)
def load_use_cases() -> dict[str, UseCaseSpec]:
    settings = get_settings()
    raw = _read_yaml(settings.catalog_dir / "use_cases.yaml")
    specs: dict[str, UseCaseSpec] = {}
    for use_case_id, body in (raw.get("use_cases") or {}).items():
        specs[use_case_id] = UseCaseSpec(use_case_id=use_case_id, **body)

    missing = [uc for uc in SUPPORTED_USE_CASE_IDS if uc not in specs]
    if missing:
        raise ValueError(f"Requirement catalog is missing use cases: {missing}")
    return specs


def get_use_case(use_case_id: str) -> UseCaseSpec | None:
    return load_use_cases().get(use_case_id)


def required_evidence_for(use_case_id: str) -> list[str]:
    """Deterministic evidence checklist lookup — no LLM in this path."""
    spec = get_use_case(use_case_id)
    return list(spec.evidence_codes) if spec else []


@lru_cache(maxsize=1)
def load_databases() -> list[DatabaseSpec]:
    settings = get_settings()
    raw = _read_yaml(settings.catalog_dir / "databases.yaml")
    specs = [DatabaseSpec(**entry) for entry in (raw.get("databases") or [])]
    return sorted(specs, key=lambda spec: spec.search_order)


def enabled_databases() -> list[DatabaseSpec]:
    """Searchable sources in configured order."""
    return [spec for spec in load_databases() if spec.enabled]


def get_database(database_id: str) -> DatabaseSpec | None:
    for spec in load_databases():
        if spec.database_id == database_id:
            return spec
    return None


def reset_catalog_cache() -> None:
    """Test hook — drops memoised config so overrides take effect."""
    load_use_cases.cache_clear()
    load_databases.cache_clear()

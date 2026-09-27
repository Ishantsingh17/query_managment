"""Pydantic runtime models (Backend Schema §3). Every downstream component returns one of these to the Orchestrator."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceStatus = Literal["AVAILABLE", "MISSING", "MANUALLY_UPLOADED", "NOT_REQUIRED"]
SelectionRole = Literal["primary", "alternative", "corroborating"]


class StructuredQuery(BaseModel):
    query_type: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    source_text: str
    requested_evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    method: str = "llm"
    rationale: str | None = None
    ambiguous_between: list[str] = Field(default_factory=list)


class RequirementItem(BaseModel):
    requirement_id: str
    query_type: str
    evidence_type: str
    evidence_description: str


class KeyRef(BaseModel):
    """One search key from the registry. `derived_from` = documented dependency on another evidence type."""
    param: str
    label: str
    derived_from: str | None = None


class EvidenceSourceMapping(BaseModel):
    evidence_type: str
    source_system: str
    source_usage_rule: str
    retrieval_method: str
    retrieval_keys: list[str]
    key_groups: list[list[KeyRef]] = Field(default_factory=list)  # AND of groups; OR within a group
    source_object_location: str | None
    expected_output_type: str

    @property
    def role(self) -> SelectionRole:
        rule = self.source_usage_rule.lower()
        if rule.startswith("alternative"):
            return "alternative"
        if rule.startswith("corroborat"):
            return "corroborating"
        return "primary"


class RetrievalPlan(BaseModel):
    """One step of the source-aware retrieval plan."""
    request_id: str
    evidence_type: str
    source_system: str
    method: str
    keys: dict[str, Any]  # resolved key values (None = must be derived from earlier evidence)
    key_names: list[str]  # every key name the step accepts
    key_groups: list[list[str]] = Field(default_factory=list)  # one value needed per group (alternatives within)
    derived: dict[str, str] = Field(default_factory=dict)  # param -> evidence type it may be taken from
    endpoint: str | None
    expected_output_type: str
    role: SelectionRole = "primary"


class CanonicalEvidence(BaseModel):
    evidence_id: str
    request_id: str
    evidence_type: str
    source_system: str
    source_reference: str
    payload_type: str
    normalized_payload: dict[str, Any]
    original_file_path: str | None = None
    retrieved_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalOutcome(BaseModel):
    evidence_type: str
    source_system: str
    found: bool
    evidence: CanonicalEvidence | None = None
    reason: str | None = None
    attempts: int = 1
    source_error: bool = False


class ValidationResult(BaseModel):
    request_id: str
    required_evidence: list[str]
    available_evidence: list[str]
    missing_evidence: list[str]
    not_required_evidence: list[str] = Field(default_factory=list)
    is_complete: bool
    reasons: dict[str, str] = Field(default_factory=dict)
    completeness_pct: int = 0


class EvidenceReviewPackage(BaseModel):
    request_id: str
    version: int
    request_summary: dict[str, Any]
    evidence_items: list[dict[str, Any]]
    validation_result: ValidationResult
    exceptions: list[dict[str, Any]]
    package_path: str
    created_at: datetime


class FinalResponsePackage(BaseModel):
    request_id: str
    approved_evidence: list[dict[str, Any]]
    response_metadata: dict[str, Any]
    package_path: str
    checksum: str
    created_at: datetime

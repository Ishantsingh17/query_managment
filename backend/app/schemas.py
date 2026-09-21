"""Pydantic contracts: the LLM output schema and the API DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

UseCaseId = Literal["UC-01", "UC-02", "UC-03", "UC-04", "UNSUPPORTED"]

ParseSource = Literal["GROQ", "RULE_BASED"]


class SearchParameters(BaseModel):
    """Parameters an auditor may supply. Every field is optional because each
    use case needs a different subset; the catalog decides what is mandatory.
    """

    model_config = ConfigDict(extra="ignore")

    period: str | None = Field(default=None, description="Accounting period, e.g. 'August 2026'")
    sob: str | None = Field(default=None, description="Set of Books identifier, e.g. '101'")
    nac_range: str | None = Field(default=None, description="NAC range, e.g. '5000-5999'")
    report_type: str | None = Field(default=None, description="Cost drill report type: AP, AR or OTHERS")
    account: str | None = Field(default=None, description="Account number, e.g. '4100'")
    schedule_type: str | None = Field(default=None, description="Schedule type where applicable")
    vendor_name: str | None = Field(default=None, description="Vendor name, e.g. 'ABC Ltd'")
    vendor_id: str | None = Field(default=None, description="Vendor identifier, e.g. 'V001'")
    invoice_number: str | None = Field(default=None, description="Invoice number, e.g. 'INV-12345'")
    # Declared nullable so the JSON schema sent to the model permits null.
    # Models routinely emit `"vendor_sample": null` for a field they have
    # nothing to say about, and a non-nullable array would make the provider
    # reject the entire tool call. The validator below normalises it back to a
    # list, so callers always receive a list.
    vendor_sample: list[str] | None = Field(
        default_factory=list, description="Vendor/sample list; null when not supplied"
    )

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("vendor_sample", mode="before")
    @classmethod
    def _null_sample_to_list(cls, value):
        return [] if value is None else value

    def provided(self) -> dict[str, Any]:
        """Only the parameters actually supplied, for display and logging."""
        data = self.model_dump(exclude_none=True)
        return {k: v for k, v in data.items() if v not in (None, "", [])}

    def to_search_context(self) -> dict[str, Any]:
        """Translate auditor-facing names into source-column names for MCP.

        'account' becomes 'account_number' to line up with the source schema.
        A single-vendor sample is promoted to vendor_name; a multi-vendor
        sample deliberately is not, so the search stays broad enough to reach
        every sampled vendor.
        """
        context: dict[str, Any] = {}
        if self.period:
            context["period"] = self.period
        if self.sob:
            context["sob"] = self.sob
        if self.nac_range:
            context["nac_range"] = self.nac_range
        if self.account:
            context["account_number"] = self.account
        if self.vendor_id:
            context["vendor_id"] = self.vendor_id
        if self.invoice_number:
            context["invoice_number"] = self.invoice_number

        vendor = self.vendor_name
        if not vendor and len(self.vendor_sample) == 1:
            vendor = self.vendor_sample[0]
        if vendor:
            context["vendor_name"] = vendor
        return context


class ParsedQuery(BaseModel):
    """The Query Understanding Agent's output contract (TRD section 5)."""

    model_config = ConfigDict(extra="ignore")

    use_case_id: UseCaseId
    requirement: str = ""
    search_parameters: SearchParameters = Field(default_factory=SearchParameters)
    confidence: float = 0.0
    # Nullable for the same reason as vendor_sample above.
    ambiguities: list[str] | None = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))

    @field_validator("ambiguities", mode="before")
    @classmethod
    def _null_ambiguities_to_list(cls, value):
        return [] if value is None else value

    @field_validator("requirement", mode="before")
    @classmethod
    def _null_requirement_to_blank(cls, value):
        return "" if value is None else value

    @property
    def is_supported(self) -> bool:
        return self.use_case_id != "UNSUPPORTED"


class ParsedQueryEnvelope(BaseModel):
    """A parse plus provenance, so the UI can say how it was produced."""

    parsed: ParsedQuery
    parse_source: ParseSource
    model: str | None = None
    fallback_reason: str | None = None


# --- API request bodies ---------------------------------------------------


class CreateAuditRequest(BaseModel):
    query: str = Field(min_length=1, description="The auditor's natural-language request")


class ClarifyRequest(BaseModel):
    """The auditor answering a request for missing mandatory inputs.

    `answer` is free text ("SOB 101, NAC 5000-5999, AP") and is re-parsed
    together with the original request. `parameters` sets values directly
    and wins over parsing. At least one must be supplied.
    """

    answer: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class MissingParameter(BaseModel):
    key: str
    label: str


class ReviewAction(BaseModel):
    action: Literal["APPROVE", "REJECT", "RETRY"]
    comment: str | None = None
    reviewer_name: str | None = None


# --- API response bodies --------------------------------------------------


class CreateAuditResponse(BaseModel):
    request_id: str
    status: str


class EvidenceChecklistItem(BaseModel):
    code: str
    label: str
    status: str  # PENDING | SEARCHING | FOUND | MISSING | VALIDATED
    identifier: str | None = None
    source_database_id: str | None = None
    source_database_name: str | None = None
    evidence_id: str | None = None
    human_required: bool = False
    # Compiled from row-level data rather than retrieved as a document.
    generated: bool = False
    row_count: int | None = None


class TimelineStep(BaseModel):
    key: str
    label: str
    status: str  # PENDING | ACTIVE | COMPLETE | ERROR
    detail: str | None = None
    sub_detail: str | None = None


class DatabaseAttemptView(BaseModel):
    database_id: str
    name: str
    status: str
    result_count: int
    requested_evidence: list[str] = Field(default_factory=list)
    newly_found: list[str] = Field(default_factory=list)
    error_message: str | None = None
    pass_number: int = 1


class EvidenceRow(BaseModel):
    evidence_id: str
    document_type: str
    document_type_label: str
    identifier: str | None
    source_database_id: str
    source_database_name: str
    status: str
    staged_file_path: str | None
    has_file: bool = False
    # Set for compiled tabular evidence: how many source rows it contains.
    row_count: int | None = None
    generated: bool = False


class ValidationCheckView(BaseModel):
    code: str
    label: str
    result: str  # PASS | FAIL | REVIEW
    detail: str | None = None


class ValidationView(BaseModel):
    validation_status: str
    checks: list[ValidationCheckView] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    headline: str
    message: str


class ParameterView(BaseModel):
    key: str
    label: str
    value: str


class UseCaseView(BaseModel):
    use_case_id: str
    name: str
    short_name: str
    description: str
    icon: str
    required_parameters: list[str]
    required_parameter_labels: list[str]
    required_evidence: list[EvidenceChecklistItem]


class AuditRequestSummary(BaseModel):
    request_id: str
    raw_query: str
    status: str
    use_case_id: str | None = None
    requirement_name: str | None = None
    created_at: str
    updated_at: str
    evidence_found: int = 0
    evidence_required: int = 0
    validation_status: str | None = None


class AuditRequestDetail(BaseModel):
    """Everything the request detail screen renders, in one payload."""

    request_id: str
    raw_query: str
    status: str
    use_case_id: str | None = None
    requirement_name: str | None = None
    created_at: str
    updated_at: str

    # Query understanding
    confidence: float | None = None
    parse_source: ParseSource | None = None
    parameters: list[ParameterView] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)

    # Evidence
    required_evidence: list[EvidenceChecklistItem] = Field(default_factory=list)
    evidence_found_count: int = 0
    evidence_required_count: int = 0
    retrieved_evidence: list[EvidenceRow] = Field(default_factory=list)

    # Progress
    timeline: list[TimelineStep] = Field(default_factory=list)
    database_attempts: list[DatabaseAttemptView] = Field(default_factory=list)
    databases_searched: int = 0

    # Outcome
    validation: ValidationView | None = None
    retry_count: int = 0
    retry_note: str | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    package_available: bool = False
    review_action: str | None = None
    reviewer_name: str | None = None
    reviewer_comment: str | None = None
    reviewed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    is_active: bool = False

    # Set while the request is halted awaiting mandatory inputs.
    missing_parameters: list[MissingParameter] = Field(default_factory=list)
    clarification_question: str | None = None
    clarification_example: str | None = None
    clarifications: list[dict[str, Any]] = Field(default_factory=list)


class PackageFile(BaseModel):
    filename: str
    document_type: str
    document_type_label: str
    identifier: str | None
    source_database_id: str
    source_database_name: str = ""
    status: str
    evidence_id: str | None = None


class TrailEntry(BaseModel):
    key: str
    label: str
    detail: str | None = None
    timestamp: str


class PackageView(BaseModel):
    request_id: str
    status: str
    package_path: str | None
    approved: bool
    approved_by: str | None = None
    approved_at: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    contents: list[PackageFile] = Field(default_factory=list)
    trail: list[TrailEntry] = Field(default_factory=list)

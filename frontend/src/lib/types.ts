/** Mirrors the Pydantic response models in backend/app/schemas.py. */

export type RequestStatus =
  | "RECEIVED"
  | "UNDERSTANDING"
  | "PLANNING"
  | "RETRIEVING"
  | "VALIDATING"
  | "INCOMPLETE"
  | "NEEDS_INPUT"
  | "READY_FOR_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "ERROR"
  | "UNSUPPORTED";

export type EvidenceStatus =
  | "PENDING"
  | "SEARCHING"
  | "FOUND"
  | "MISSING"
  | "VALIDATED";

export type StepStatus = "PENDING" | "ACTIVE" | "COMPLETE" | "ERROR";

export type CheckResult = "PASS" | "FAIL" | "REVIEW";

export type ValidationStatus =
  | "COMPLETE"
  | "INCOMPLETE"
  | "NEEDS_REVIEW"
  | "ERROR";

export interface EvidenceChecklistItem {
  code: string;
  label: string;
  status: EvidenceStatus;
  identifier: string | null;
  source_database_id: string | null;
  source_database_name: string | null;
  evidence_id: string | null;
  human_required: boolean;
  /** Compiled from row-level data rather than retrieved as a document. */
  generated: boolean;
  row_count: number | null;
}

export interface TimelineStep {
  key: string;
  label: string;
  status: StepStatus;
  detail: string | null;
  sub_detail: string | null;
}

export interface DatabaseAttempt {
  database_id: string;
  name: string;
  status: string;
  result_count: number;
  requested_evidence: string[];
  newly_found: string[];
  error_message: string | null;
  pass_number: number;
}

export interface EvidenceRow {
  evidence_id: string;
  document_type: string;
  document_type_label: string;
  identifier: string | null;
  source_database_id: string;
  source_database_name: string;
  status: EvidenceStatus;
  staged_file_path: string | null;
  has_file: boolean;
  /** Set for compiled tabular evidence: how many source rows it contains. */
  row_count: number | null;
  generated: boolean;
}

export interface ValidationCheck {
  code: string;
  label: string;
  result: CheckResult;
  detail: string | null;
}

export interface Validation {
  validation_status: ValidationStatus;
  checks: ValidationCheck[];
  missing_evidence: string[];
  headline: string;
  message: string;
}

export interface MissingParameter {
  key: string;
  label: string;
}

export interface Clarification {
  answer: string | null;
  parameters: Record<string, unknown>;
  at: string;
}

export interface ParameterView {
  key: string;
  label: string;
  value: string;
}

export interface UseCase {
  use_case_id: string;
  name: string;
  short_name: string;
  description: string;
  icon: string;
  required_parameters: string[];
  required_parameter_labels: string[];
  required_evidence: EvidenceChecklistItem[];
}

export interface AuditRequestSummary {
  request_id: string;
  raw_query: string;
  status: RequestStatus;
  use_case_id: string | null;
  requirement_name: string | null;
  created_at: string;
  updated_at: string;
  evidence_found: number;
  evidence_required: number;
  validation_status: ValidationStatus | null;
}

export interface AuditRequestDetail {
  request_id: string;
  raw_query: string;
  status: RequestStatus;
  use_case_id: string | null;
  requirement_name: string | null;
  created_at: string;
  updated_at: string;

  confidence: number | null;
  parse_source: "GROQ" | "RULE_BASED" | null;
  parameters: ParameterView[];
  ambiguities: string[];

  required_evidence: EvidenceChecklistItem[];
  evidence_found_count: number;
  evidence_required_count: number;
  retrieved_evidence: EvidenceRow[];

  timeline: TimelineStep[];
  database_attempts: DatabaseAttempt[];
  databases_searched: number;

  validation: Validation | null;
  retry_count: number;
  retry_note: string | null;
  missing_evidence: string[];
  package_available: boolean;
  review_action: string | null;
  reviewer_name: string | null;
  reviewer_comment: string | null;
  reviewed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  is_active: boolean;

  /** Set while the request is halted awaiting mandatory inputs. */
  missing_parameters: MissingParameter[];
  clarification_question: string | null;
  clarification_example: string | null;
  clarifications: Clarification[];
}

export interface PackageFile {
  filename: string;
  document_type: string;
  document_type_label: string;
  identifier: string | null;
  source_database_id: string;
  source_database_name?: string;
  status: string;
  evidence_id: string | null;
}

export interface TrailEntry {
  key: string;
  label: string;
  detail: string | null;
  timestamp: string;
}

export interface PackageSummary {
  request_id?: string;
  original_query?: string;
  use_case_id?: string;
  requirement_name?: string;
  extracted_inputs?: Record<string, unknown>;
  /** Auditor-facing labels from the requirement catalog. */
  parameters?: ParameterView[];
  required_evidence?: string[];
  found_evidence?: string[];
  missing_evidence?: string[];
  databases_searched?: string[];
  validation_status?: string;
  retry_count?: number;
  evidence_count?: number;
  retry_note?: string | null;
  reviewer_status?: string | null;
}

export interface PackageView {
  request_id: string;
  status: RequestStatus;
  package_path: string | null;
  approved: boolean;
  approved_by: string | null;
  approved_at: string | null;
  summary: PackageSummary;
  contents: PackageFile[];
  trail: TrailEntry[];
}

export type ReviewActionType = "APPROVE" | "REJECT" | "RETRY";

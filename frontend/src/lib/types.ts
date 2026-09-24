export type Role = 'AUDITOR' | 'VALIDATOR' | 'SME'

export interface User {
  user_id: string
  email: string
  full_name: string
  first_name: string
  role: Role
  title: string
  initials: string
}

export interface Counts {
  required: number
  available: number
  missing: number
  manual: number
  not_required: number
  completeness_pct: number
}

export interface RequestRow {
  request_id: string
  query_type: string | null
  query_type_label: string
  status: string
  status_label: string
  validation_status: string | null
  approval_status: string | null
  notification_status: string | null
  created_at: string
  updated_at: string
  due_at: string | null
  completeness_pct: number
  counts: Counts | null
  missing_evidence: string[]
  submitted_at?: string
  decision?: 'APPROVE' | 'REJECT' | null
  decided_at?: string
  final_response_ready?: boolean
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface Evidence {
  evidence_id: string | null
  evidence_type: string
  label: string
  short_label?: string
  icon: string
  source_system: string | null
  source_reference: string | null
  retrieval_method?: string | null
  payload_type?: string | null
  status: 'AVAILABLE' | 'MISSING' | 'MANUALLY_UPLOADED' | 'NOT_REQUIRED' | 'PENDING'
  reason?: string | null
  description: string | null
  notes?: string[]
  corroboration?: { source_system: string; matched: boolean; reference: string | null }[]
  uploaded_by?: string | null
  justification?: string | null
  has_file: boolean
  is_approved?: boolean
  requirement_id?: string
  evidence_description?: string
}

export interface EventItem {
  id: number
  stage: string
  type: 'success' | 'warning' | 'info' | 'progress' | 'submit' | 'error'
  title: string
  detail: string | null
  actor_name: string | null
  actor_role: string | null
  created_at: string
}

export interface Decision {
  action: 'APPROVE' | 'REJECT'
  comment: string | null
  acted_at: string
  approver_name: string | null
  approver_title: string | null
  approver_initials: string | null
}

export interface RequestDetail extends RequestRow {
  original_query: string
  understanding: DetailUnderstanding | null
  auditor_name: string | null
  parameters: Record<string, string>
  stepper: { label: string; state: 'done' | 'current' | 'todo' }[]
  evidence: Evidence[]
  events: EventItem[]
  validated_by: string | null
  validator_note: string | null
  validated_at: string | null
  decisions: Decision[]
  has_review_package: boolean
  has_final_package: boolean
  actions: string[]
}

export interface Summary {
  role: Role
  auditor: { total: number; processing: number; awaiting_review: number; completed: number; mom_delta: number; on_time_pct: number }
  badges: { review_queue: number; needs_attention: number; approvals: number }
  sme?: { awaiting: number; due_soon: number; approved: number; rejected: number; total_reviewed: number; avg_days: number }
}

export interface FinalPackage {
  request_id: string
  approved_evidence: (Evidence & { package_file?: string; sha256?: string })[]
  response_metadata: {
    query_type_label: string
    original_query: string
    approval: { approver_name: string; approver_title: string; comment: string | null; acted_at: string }
    sealed: boolean
  }
  checksum: string
  created_at: string
}

export interface RequiredParameter {
  params: string[]
  label: string
  satisfied: boolean
  value: string | null
}

export interface MissingParameter {
  param: string
  label: string
  alternatives: { param: string; label: string }[]
}

export interface Understanding {
  query_type: string | null
  query_type_label: string | null
  classification_status: 'identified' | 'ambiguous' | 'unsupported' | 'invalid_selection'
  rationale: string | null
  candidates: { value: string; label: string }[]
  supported_query_types: { value: string; label: string }[]
  parameters: { param: string; label: string; value: string }[]
  period: string | null
  evidence_requested: { evidence_type: string; label: string; description?: string }[]
  required_parameters: RequiredParameter[]
  missing_parameters: MissingParameter[]
  parameter_status: 'COMPLETE' | 'ACTION_REQUIRED' | 'NOT_APPLICABLE'
  retrieval_status: 'READY' | 'WAITING_FOR_PARAMETERS' | 'NEEDS_CLARIFICATION' | 'UNSUPPORTED'
  message: string
}

export interface DetailUnderstanding {
  query_type_label: string
  parameters: { param: string; label: string; value: string }[]
  period: string | null
  evidence_requested: { evidence_type: string; label: string }[]
  required_parameters: RequiredParameter[]
  parameter_status: 'COMPLETE' | 'ACTION_REQUIRED'
}

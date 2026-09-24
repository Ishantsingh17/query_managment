"""SQLite Request DB schema.

The seven tables from the Backend Schema document use the exact agreed column names.
`users` and `request_events` are additive support tables (role abstraction and the
workflow audit trail shown in the Activity panel / Status drawer).
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---- Configuration tables (exact stakeholder schemas) -------------------------------------------

class RequirementCatalog(Base):
    __tablename__ = "requirement_catalog"
    requirement_id: Mapped[str] = mapped_column(String, primary_key=True)
    query_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    evidence_description: Mapped[str] = mapped_column(Text, nullable=False)


class EvidenceSourceRegistry(Base):
    __tablename__ = "evidence_source_registry"
    evidence_type: Mapped[str] = mapped_column(String, primary_key=True)
    source_system: Mapped[str] = mapped_column(String, primary_key=True)
    source_usage_selection_rule: Mapped[str] = mapped_column(String, nullable=False)
    retrieval_method: Mapped[str] = mapped_column(String, nullable=False)
    search_retrieval_keys: Mapped[str] = mapped_column(String, nullable=False)
    source_object_location: Mapped[str] = mapped_column(String, nullable=True)
    expected_output_type: Mapped[str] = mapped_column(String, nullable=False)


class QueryTypeDefinition(Base):
    """Stakeholder Query Type definitions: display name, evidence summary and automation behaviour/context.
    Kept separate so the Requirement Catalog keeps its exact 4-field schema."""
    __tablename__ = "query_type_definitions"
    query_type: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    evidence_required: Mapped[str] = mapped_column(Text, nullable=False)
    automation_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    classification_keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")


# ---- Workflow tables ----------------------------------------------------------------------------

class RequestRecord(Base):
    __tablename__ = "requests"
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    auditor_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    structured_query_json: Mapped[str | None] = mapped_column(Text)
    query_type: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    validation_status: Mapped[str | None] = mapped_column(String)
    approval_status: Mapped[str | None] = mapped_column(String)
    review_package_path: Mapped[str | None] = mapped_column(String)
    final_response_path: Mapped[str | None] = mapped_column(String)
    notification_status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.request_id"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    source_system: Mapped[str | None] = mapped_column(String)
    source_reference: Mapped[str | None] = mapped_column(String)
    retrieval_method: Mapped[str | None] = mapped_column(String)
    payload_type: Mapped[str | None] = mapped_column(String)
    file_path: Mapped[str | None] = mapped_column(String)
    normalized_payload_json: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String, nullable=False)
    validation_reason: Mapped[str | None] = mapped_column(Text)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApprovalAction(Base):
    __tablename__ = "approval_actions"
    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.request_id"), nullable=False, index=True)
    approver_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ManualUpload(Base):
    __tablename__ = "manual_uploads"
    upload_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.request_id"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    notification_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.request_id"), nullable=False, index=True)
    recipient: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    application_link: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


# ---- Support tables -----------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # AUDITOR | VALIDATOR | SME
    title: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    notification_email: Mapped[str | None] = mapped_column(String)


class RequestEvent(Base):
    __tablename__ = "request_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.request_id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # success | warning | info | progress | submit | error
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    actor_name: Mapped[str | None] = mapped_column(String)
    actor_role: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# Exact agreed column sets, validated at startup.
EXPECTED_SCHEMAS: dict[str, list[str]] = {
    "query_type_definitions": ["query_type", "display_name", "evidence_required", "automation_behavior",
                               "classification_keywords"],
    "requirement_catalog": ["requirement_id", "query_type", "evidence_type", "evidence_description"],
    "evidence_source_registry": [
        "evidence_type", "source_system", "source_usage_selection_rule", "retrieval_method",
        "search_retrieval_keys", "source_object_location", "expected_output_type",
    ],
    "requests": [
        "request_id", "auditor_id", "original_query", "structured_query_json", "query_type", "status",
        "validation_status", "approval_status", "review_package_path", "final_response_path",
        "notification_status", "created_at", "updated_at",
    ],
    "evidence_items": [
        "evidence_id", "request_id", "evidence_type", "source_system", "source_reference", "retrieval_method",
        "payload_type", "file_path", "normalized_payload_json", "validation_status", "validation_reason",
        "is_approved", "created_at",
    ],
    "approval_actions": ["approval_id", "request_id", "approver_id", "action", "comment", "acted_at"],
    "manual_uploads": ["upload_id", "request_id", "evidence_type", "file_path", "uploaded_by", "uploaded_at", "notes"],
    "notification_events": [
        "notification_id", "request_id", "recipient", "event_type", "channel", "status",
        "application_link", "sent_at", "error_message",
    ],
}

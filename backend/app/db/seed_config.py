"""Seed/migration script for the stakeholder configuration (Query Type Definitions, Requirement Catalog,
Evidence Source Registry) and dev users.

Run: python -m app.db.seed_config
The configuration tables are replaced with the authoritative set on every run, so rows that are
not in the stakeholder configuration (e.g. earlier demo Query Types) are removed.
"""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import EvidenceSourceRegistry, QueryTypeDefinition, RequirementCatalog, User
from app.db.session import create_schema, session_scope, validate_schema
from app.db.stakeholder_config import EVIDENCE_SOURCE_REGISTRY, QUERY_TYPE_DEFINITIONS, REQUIREMENT_CATALOG

DEV_PASSWORD = "Password@123"

USERS = [
    # user_id, email, full_name, role, title
    ("U-AUD-001", "sarah.mitchell@company.com", "Sarah Mitchell", "AUDITOR", "Senior Auditor"),
    ("U-VAL-001", "david.okafor@company.com", "David Okafor", "VALIDATOR", "Human Validator"),
    ("U-SME-001", "priya.raman@company.com", "Priya Raman", "SME", "Finance SME · Approver"),
]


def seed_config(session: Session) -> None:
    session.execute(delete(QueryTypeDefinition))
    session.execute(delete(RequirementCatalog))
    session.execute(delete(EvidenceSourceRegistry))
    session.flush()
    for qt, name, evidence, automation, keywords in QUERY_TYPE_DEFINITIONS:
        session.add(QueryTypeDefinition(query_type=qt, display_name=name, evidence_required=evidence,
                                        automation_behavior=automation, classification_keywords=keywords))
    for rid, qt, et, desc in REQUIREMENT_CATALOG:
        session.add(RequirementCatalog(requirement_id=rid, query_type=qt, evidence_type=et, evidence_description=desc))
    for et, src, rule, method, keys, loc, out in EVIDENCE_SOURCE_REGISTRY:
        session.add(EvidenceSourceRegistry(
            evidence_type=et, source_system=src, source_usage_selection_rule=rule, retrieval_method=method,
            search_retrieval_keys=keys, source_object_location=loc, expected_output_type=out,
        ))
    for uid, email, name, role, title in USERS:
        if session.get(User, uid) is None:
            session.add(User(user_id=uid, email=email, full_name=name, role=role, title=title,
                             password_hash=hash_password(DEV_PASSWORD), notification_email=email))
    session.flush()
    from app.registry.resolution import refresh_label_cache
    refresh_label_cache(session)


def main() -> None:
    create_schema()
    with session_scope() as s:
        seed_config(s)
        n = len(list(s.scalars(select(QueryTypeDefinition.query_type))))
    validate_schema()
    print(f"Stakeholder configuration loaded ({n} query types) and validated.")


if __name__ == "__main__":
    main()

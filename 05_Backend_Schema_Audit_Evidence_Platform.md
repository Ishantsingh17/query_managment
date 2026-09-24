| **Document status**  | Draft for development                        |
|----------------------|----------------------------------------------|
| **Working baseline** | Updated production architecture              |
| **Scope**            | Backend + Agentic + defined Web App behavior |
| **Application**      | Audit Evidence Platform                      |

| Schema principle: Requirement Catalog and Evidence Source Registry are stored as SQLite tables only. Request metadata and workflow state also live in SQLite. Evidence files live on the local filesystem. |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. Logical Data Model

Request  
- request_id  
- auditor_id  
- original_query  
- structured_query  
- query_type  
- status / stage  
- validation_status  
- approval_status  
- package references  
\|  
\< Request -\> Evidence Items -\> Source Attribution \>  
\|  
\< Request -\> Review Package -\> Approval -\> Final Package \>

# 2. Core SQLite Tables

| **Table**                | **Key fields**                                                                                                                                                                                                       | **Purpose**                                                                                        |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| requirement_catalog      | requirement_id (PK), query_type, evidence_type, evidence_description                                                                                                                                                 | Authoritative required-evidence definition by Query Type.                                          |
| evidence_source_registry | evidence_type, source_system, source_usage_selection_rule, retrieval_method, search_retrieval_keys, source_object_location, expected_output_type                                                                     | Authoritative mapping of required evidence to applicable source systems and API retrieval details. |
| requests                 | request_id (PK), auditor_id, original_query, structured_query_json, query_type, status, validation_status, approval_status, review_package_path, final_response_path, notification_status, created_at, updated_at    | System of record for request lifecycle and package references.                                     |
| evidence_items           | evidence_id (PK), request_id (FK), evidence_type, source_system, source_reference, retrieval_method, payload_type, file_path, normalized_payload_json, validation_status, validation_reason, is_approved, created_at | Tracks each evidence item and its provenance.                                                      |
| approval_actions         | approval_id (PK), request_id (FK), approver_id, action, comment, acted_at                                                                                                                                            | Stores SME approve/reject decisions.                                                               |
| manual_uploads           | upload_id (PK), request_id (FK), evidence_type, file_path, uploaded_by, uploaded_at, notes                                                                                                                           | Tracks manually supplied evidence.                                                                 |
| notification_events      | notification_id (PK), request_id (FK), recipient, event_type, channel, status, application_link, sent_at, error_message                                                                                              | Tracks Gmail notification attempts and outcomes.                                                   |

# 3. Pydantic Runtime Models

| **Model**             | **Representative fields**                                                                                                                             |
|-----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| StructuredQuery       | query_type?, parameters: dict\[str, Any\], source_text                                                                                                |
| RequirementItem       | requirement_id, query_type, evidence_type, evidence_description                                                                                       |
| EvidenceSourceMapping | evidence_type, source_system, source_usage_rule, retrieval_method, retrieval_keys, source_object_location, expected_output_type                       |
| RetrievalPlan         | request_id, evidence_type, source_system, method, keys, endpoint/object, expected_output_type                                                         |
| CanonicalEvidence     | evidence_id, request_id, evidence_type, source_system, source_reference, payload_type, normalized_payload, original_file_path, retrieved_at, metadata |
| ValidationResult      | request_id, required_evidence, available_evidence, missing_evidence, is_complete, reasons                                                             |
| EvidenceReviewPackage | request_id, request_summary, evidence_items, validation_result, exceptions, package_path                                                              |
| FinalResponsePackage  | request_id, approved_evidence, response_metadata, package_path                                                                                        |

# 4. Requirement Catalog — SQLite Table Schema

| **Column**           | **Required?** | **Example**                      |
|----------------------|---------------|----------------------------------|
| Requirement ID       | Yes           | REQ-001                          |
| Query Type           | Yes           | PAYMENT_TESTING                  |
| Evidence Type        | Yes           | INVOICE                          |
| Evidence Description | Yes           | Invoice copy for selected sample |

# 5. Evidence Source Registry — SQLite Table Schema

| **Column**                    | **Required?**          | **Example / interpretation**                                                        |
|-------------------------------|------------------------|-------------------------------------------------------------------------------------|
| Evidence Type                 | Yes                    | PO                                                                                  |
| Source System                 | Yes                    | GESS                                                                                |
| Source Usage / Selection Rule | Yes / business-defined | Must retrieve / alternative / corroborating; do not assume priority unless defined. |
| Retrieval Method              | Yes                    | APIs                                                                                |
| Search / Retrieval Keys       | Yes                    | PO Number                                                                           |
| Source Object / Location      | As available           | AP API / document repository                                                        |
| Expected Output Type          | Yes                    | Structured data and/or PDF and/or Excel and/or CSV and/or JPG                       |

# 6. Request State Machine

REQUEST_CREATED  
-\> PROCESSING  
-\> VALIDATION_PENDING  
-\> REWORK_REQUIRED -\> PROCESSING / MANUAL_UPLOAD -\> VALIDATION_PENDING  
-\> REVIEW_READY  
-\> SME_REVIEW  
-\> REJECTED -\> REWORK_REQUIRED  
-\> APPROVED -\> FINAL_RESPONSE_READY  
-\> NOTIFIED -\> COMPLETED

# 7. File/Directory Structure

/app  
/storage  
/evidence_staging/\<request_id\>/  
/original/  
/normalized/  
/manual_uploads/  
/packages/\<request_id\>/  
evidence_review_package.json  
final_response_package.json  
supporting_files/  
/db  
audit_evidence.sqlite  
  
SQLite tables inside audit_evidence.sqlite:  
requirement_catalog  
evidence_source_registry  
requests  
evidence_items  
approval_actions  
manual_uploads  
notification_events

Retrieval rule: All source evidence is retrieved through APIs only. The development environment uses mock APIs backed by SQLite source datasets.

# 8. API Surface

| **Endpoint**                                        | **Purpose**                                         |
|-----------------------------------------------------|-----------------------------------------------------|
| POST /api/requests                                  | Create a new audit request.                         |
| GET /api/requests/{request_id}                      | Get request status and package references.          |
| GET /api/requests                                   | List requests for the signed-in role.               |
| POST /api/requests/{request_id}/retry               | Start retrieval/rework for the request.             |
| POST /api/requests/{request_id}/evidence-upload     | Upload missing evidence manually.                   |
| POST /api/requests/{request_id}/accept-not-required | Mark an evidence item as not required and continue. |
| POST /api/requests/{request_id}/approve             | SME approval action.                                |
| POST /api/requests/{request_id}/reject              | SME rejection action with comment.                  |
| GET /api/requests/{request_id}/package              | Return package metadata and application link.       |

| **Security boundary:** Role-based authorization must be enforced in the API/backend, not by the LLM. Source access should remain behind MCP/source connectors and use controlled credentials. |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

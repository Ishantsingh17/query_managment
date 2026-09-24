| **Document status**  | Draft for development                        |
|----------------------|----------------------------------------------|
| **Working baseline** | Updated production architecture              |
| **Scope**            | Backend + Agentic + defined Web App behavior |
| **Application**      | Audit Evidence Platform                      |

| Purpose: Define the business and product requirements for the updated end-to-end audit evidence retrieval workflow, using the confirmed architecture, SQLite configuration tables, API-based retrieval, and development decisions. |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. Product Overview

The Audit Evidence Platform enables an auditor to submit a natural-language evidence request and receive a validated, SME-approved evidence package through a controlled workflow. The platform combines query understanding, deterministic catalog and registry lookups, agentic retrieval orchestration, MCP-based integrations, evidence normalization, completeness validation, human review, final approval, and notification.

# 2. Goals

- Automate evidence identification and retrieval across multiple enterprise source systems.

- Use the Requirement Catalog and Evidence Source Registry as controlled SQLite tables rather than allowing agents to invent required evidence or source mappings.

- Provide a consistent internal Canonical Evidence Model across heterogeneous source responses.

- Ensure required evidence is complete before approval, while supporting retry/rework and manual evidence upload for missing or unclear items.

- Provide a structured review package for the Final Approver (SME) and a final response package for the auditor.

- Keep the design aligned with production architecture while using SQLite and local file storage for development and integration testing.

# 3. In Scope

| **Area**                       | **Requirement**                                                                                                      |
|--------------------------------|----------------------------------------------------------------------------------------------------------------------|
| User access                    | One web application with role-based experiences for Auditor, Human Validator, and Final Approver.                    |
| Query intake                   | Natural-language query submission through the Auditor Portal / Grid.                                                 |
| Agentic orchestration          | Orchestrator controls the end-to-end workflow and collects outputs from downstream agents/components.                |
| Query understanding            | Query Understanding Agent creates a Structured Query and extracts business parameters present in the request.        |
| Query type                     | Query Type Classification identifies the Query Type.                                                                 |
| Controlled evidence definition | Requirement Catalog maps Query Type to required evidence.                                                            |
| Controlled source mapping      | Evidence Source Registry maps evidence to applicable source systems and retrieval details.                           |
| Retrieval                      | Retrieval Planning + Retrieval Agent execute source-aware retrieval through MCP.                                     |
| Source integration             | Development uses mock APIs backed by SQLite data for enterprise source systems; all evidence retrieval is API-based. |
| Evidence processing            | Document/data extraction, normalization, and Canonical Evidence Model.                                               |
| Validation                     | Completeness check only at this stage. Additional validation rules are deferred until provided.                      |
| Human workflow                 | Human Validator can retry/rework, upload evidence manually, or accept that an item is not required.                  |
| Final approval                 | SME is the Final Approver and approves or rejects the Evidence Review Package in the application.                    |
| Response packaging             | Orchestrator prepares both the pre-approval Evidence Review Package and post-approval Final Response Package.        |
| Notification                   | Gmail notification with an application link.                                                                         |
| Storage                        | SQLite Request DB and local evidence/file staging.                                                                   |

# 4. Out of Scope / Deferred

- Advanced validation rules beyond completeness because stakeholder rule configuration has not yet been provided.

- Production enterprise API implementations; development will use mock APIs aligned to the eventual API contracts.

- Final enterprise identity provider configuration and production infrastructure specifics.

- Any separate Response Generation Agent; response-package assembly is owned by the Orchestrator.

- Unconfirmed document-processing technology choices such as mandatory OCR or a specific file parser.

# 5. User Roles

| **Role**              | **Primary responsibilities**                                                                                                  |
|-----------------------|-------------------------------------------------------------------------------------------------------------------------------|
| Auditor               | Submit requests, monitor status, open final response packages, and access approved evidence.                                  |
| Human Validator       | Resolve missing/unclear evidence, trigger retry/rework, manually upload evidence, or accept an evidence item as not required. |
| Final Approver (SME)  | Review the Evidence Review Package and approve or reject it.                                                                  |
| System / Orchestrator | Coordinate the complete workflow, maintain request state, collect agent outputs, and assemble response packages.              |

# 6. Functional Requirements

| **ID** | **Requirement**         | **Description**                                                                                                                                                                           |
|--------|-------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FR-01  | Authenticate user       | Application must authenticate the user and apply role-based access.                                                                                                                       |
| FR-02  | Create request          | System must create a Request ID and persist the initial request metadata in Request DB.                                                                                                   |
| FR-03  | Understand request      | Query Understanding Agent must create a Structured Query from the natural-language request.                                                                                               |
| FR-04  | Classify query type     | System must identify the Query Type before evidence requirements are resolved.                                                                                                            |
| FR-05  | Resolve requirements    | Requirement Catalog SQLite table must determine required evidence for the Query Type using the agreed four-field schema: Requirement ID, Query Type, Evidence Type, Evidence Description. |
| FR-06  | Resolve source mappings | Evidence Source Registry SQLite table must determine applicable source mappings and retrieval keys using the agreed seven-field schema.                                                   |
| FR-07  | Plan retrieval          | Retrieval Planning must create a source-aware retrieval plan.                                                                                                                             |
| FR-08  | Retrieve via MCP        | Retrieval Agent must execute retrieval through MCP and source-specific connectors.                                                                                                        |
| FR-09  | Normalize evidence      | System must convert retrieved outputs to the Canonical Evidence Model while preserving provenance.                                                                                        |
| FR-10  | Validate completeness   | Validation Engine must compare required evidence with available evidence and determine completeness.                                                                                      |
| FR-11  | Recover gaps            | System must support retry/rework, manual upload, or accept-not-required for incomplete cases.                                                                                             |
| FR-12  | Prepare review package  | Orchestrator must collect request, evidence, and validation outputs into an Evidence Review Package.                                                                                      |
| FR-13  | Notify SME              | System must notify the SME with an application link when the review package is ready.                                                                                                     |
| FR-14  | Approve/reject          | SME must be able to approve or reject the package in the application.                                                                                                                     |
| FR-15  | Prepare final package   | After approval, Orchestrator must assemble the Final Response Package from SME-approved evidence only.                                                                                    |
| FR-16  | Notify auditor          | System must notify the auditor with an application link to the final package.                                                                                                             |

# 7. Key Product States

| **State**            | **Meaning**                                                                       |
|----------------------|-----------------------------------------------------------------------------------|
| REQUEST_CREATED      | Request record created; processing not yet completed.                             |
| PROCESSING           | Agents and retrieval workflow are executing.                                      |
| VALIDATION_PENDING   | Retrieved evidence is available for completeness evaluation.                      |
| REWORK_REQUIRED      | Evidence is missing or processing/retrieval requires retry or human intervention. |
| REVIEW_READY         | Evidence Review Package has been assembled and awaits SME review.                 |
| APPROVED             | SME has approved the review package.                                              |
| REJECTED             | SME has rejected the package and the request requires rework.                     |
| FINAL_RESPONSE_READY | Final Response Package is prepared and stored.                                    |
| NOTIFIED             | Auditor notification with application link has been sent.                         |
| COMPLETED            | Request lifecycle is complete.                                                    |

# 8. Success Criteria

- A valid supported query can move from submission through retrieval, completeness validation, SME approval, final response packaging, and auditor notification without manual intervention unless evidence is missing/unclear.

- All retrieved evidence remains traceable to its source system and source reference.

- The SME always sees a structured review package rather than raw internal agent output.

- The Final Response Package contains only SME-approved evidence.

- The architecture supports multiple source systems for a single request.

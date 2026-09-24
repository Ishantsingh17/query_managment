| **Document status**  | Draft for development                        |
|----------------------|----------------------------------------------|
| **Working baseline** | Updated production architecture              |
| **Scope**            | Backend + Agentic + defined Web App behavior |
| **Application**      | Audit Evidence Platform                      |

| **Implementation approach:** Build a fresh implementation from the updated architecture, with stable contracts and mock integrations first, then swap in the real source APIs when those APIs are available. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. Workstreams

| **Workstream**      | **Deliverables**                                                                                            |
|---------------------|-------------------------------------------------------------------------------------------------------------|
| Foundation          | Repository structure, Python environment, FastAPI skeleton, configuration management, logging, error model. |
| Configuration       | SQLite Requirement Catalog and Evidence Source Registry tables; Pydantic models and seed/migration scripts. |
| Orchestration       | Orchestrator state graph, request lifecycle, agent invocation, package assembly.                            |
| Agentic             | Query Understanding, Query Type Classification, Retrieval Planning, Retrieval Agent.                        |
| MCP                 | MCP gateway/layer and source-specific connector contracts.                                                  |
| Source mocks        | Mock APIs backed by SQLite for Oracle, GRS, VMS, GESS, LMS, ARIBA, GPS, GROSS, IPAMS.                       |
| Evidence processing | Extraction/Parsing interface, normalization, Canonical Evidence Model, staging.                             |
| Validation          | Completeness-only Validation Engine.                                                                        |
| Human workflow      | Validation Review Portal behavior, manual upload, retry/rework, accept-not-required.                        |
| Approval workflow   | SME review, approve/reject, package status handling.                                                        |
| Notifications       | Gmail Notification Service with application link.                                                           |
| Web application     | Auditor, Validation/Review, and Final Approver screens with clean, compact UX.                              |
| Testing             | Unit, integration, end-to-end, connector contract, failure-path testing.                                    |

# 2. Suggested Delivery Sequence

## Step 1 - Project foundation

Set up repository, FastAPI app, environment configuration, structured logging, base error handling, and SQLite connectivity.

## Step 2 - Configuration intake

Create the Requirement Catalog and Evidence Source Registry as SQLite tables using the exact agreed schemas. Add seed/migration scripts and validate the table structure at startup.

## Step 3 - Request lifecycle

Create Request DB schema, request APIs, role-aware request states, and basic workflow persistence.

## Step 4 - Orchestrator

Implement the end-to-end state graph and request context object. Ensure every downstream component returns structured output to the Orchestrator.

## Step 5 - Query understanding and classification

Implement Structured Query creation and Query Type identification. Add controlled outputs and validation against supported Query Types.

## Step 6 - Registry resolution and retrieval planning

Resolve required evidence and applicable sources from configuration. Build source-aware retrieval plans.

## Step 7 - MCP + mock source APIs

Implement MCP layer and source connector interfaces. Create mock API endpoints backed by SQLite datasets representing the confirmed enterprise sources. All source evidence retrieval will use APIs; the mock APIs will mirror the future source API contracts.

## Step 8 - Evidence processing

Implement extraction/parsing abstraction, normalization, Canonical Evidence Model, and local evidence staging.

## Step 9 - Completeness validation

Compare required evidence against available evidence. Implement retry/manual upload/accept-not-required routing.

## Step 10 - Review and approval

Build Evidence Review Package, update Request DB, send Gmail notification, and enable SME approval/rejection.

## Step 11 - Final response packaging

After SME approval, let the Orchestrator assemble the Final Response Package from approved evidence only, persist it, and update Request DB.

## Step 12 - Auditor notification

Send Gmail notification with application link and surface the final response in Auditor Portal / Grid.

## Step 13 - Hardening

Add tests for multi-source requests, missing evidence, source failures, rejected approvals, duplicate submissions, and package-generation failures.

## Step 14 - Real API integration readiness

Replace mock source adapters with real API adapters once the source teams provide API contracts and implementations. Keep connector contracts stable.

# 3. Mock Data Strategy

- Create representative SQLite datasets for each source application rather than random synthetic rows.

- Include positive cases where all required evidence exists.

- Include multi-source cases where one query requires evidence from several systems.

- Include missing-evidence cases to exercise retry and manual-upload paths.

- Include mismatched identifiers to test key/dependency handling and completeness outcomes.

- Keep the data schema behind the mock API contract so the retrieval agent does not depend on SQLite-specific details.

# 4. Definition of Done

| **Area**         | **Completion condition**                                                                                                        |
|------------------|---------------------------------------------------------------------------------------------------------------------------------|
| Configuration    | Both SQLite configuration tables are created, validated, and populated with representative data using the exact agreed schemas. |
| Orchestration    | A single request can traverse the full workflow with persisted state.                                                           |
| Retrieval        | Multi-source retrieval works through MCP using mock APIs.                                                                       |
| Evidence model   | Every retrieved evidence item has source attribution and canonical representation.                                              |
| Validation       | Completeness check correctly identifies complete/incomplete requests.                                                           |
| Human validation | Retry, manual upload, and accept-not-required paths work.                                                                       |
| SME approval     | SME can review and approve/reject the Evidence Review Package.                                                                  |
| Final response   | Orchestrator creates the Final Response Package from approved evidence only.                                                    |
| Notification     | Gmail notification is sent with an application link.                                                                            |
| UI               | Role-specific screens are clean, responsive, and compact with limited scrolling.                                                |
| Testing          | Critical happy paths and failure paths are covered by automated tests.                                                          |

# 5. Dependency / Input Checklist

| **Input**                                  | **Needed to start?**            | **Notes**                                                                                                                                                                                                            |
|--------------------------------------------|---------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Requirement Catalog                        | Yes                             | Use the confirmed four-field schema: Requirement ID, Query Type, Evidence Type, Evidence Description; store in SQLite table.                                                                                         |
| Evidence Source Registry                   | Yes                             | Use the confirmed seven-field schema: Evidence Type, Source System, Source Usage / Selection Rule, Retrieval Method, Search / Retrieval Keys, Source Object / Location, Expected Output Type; store in SQLite table. |
| Source API contracts                       | Yes for integration design      | Endpoints, methods, parameters, authentication, sample requests/responses, errors; all evidence retrieval is API-based.                                                                                              |
| Actual source API implementation           | No for initial development      | Use mock APIs until live services are available.                                                                                                                                                                     |
| Validation rules                           | No beyond completeness          | Completeness is implemented now; additional rules can be plugged in later.                                                                                                                                           |
| Production identity/security configuration | No for initial build            | Use role abstractions and mock/local configuration while building.                                                                                                                                                   |
| Document processing details                | Not required to start framework | Implement an extraction interface and defer exact method selection where formats are not confirmed.                                                                                                                  |

# 6. Immediate Next Development Actions

1.  Create the repository and base FastAPI service structure.

2.  Add representative seed data for the Requirement Catalog and Evidence Source Registry using the agreed SQLite table schemas.

3.  Define Pydantic models for request, requirement, source mapping, retrieval plan, canonical evidence, validation result, review package, and final response package.

4.  Create SQLite schemas for Request DB and source mock datasets.

5.  Define MCP tool contracts and connector interfaces around future source API contracts.

6.  Implement the Orchestrator skeleton and request state machine before adding individual agents.

7.  Build one complete happy-path query end-to-end, then add the other Query Types and failure branches.

8.  Add Gmail Notification Service behind a provider interface and configure the development sender account.

9.  Build the role-specific application views after the backend contracts are stable.

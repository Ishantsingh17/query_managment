| **Document status**  | Draft for development                        |
|----------------------|----------------------------------------------|
| **Working baseline** | Updated production architecture              |
| **Scope**            | Backend + Agentic + defined Web App behavior |
| **Application**      | Audit Evidence Platform                      |

| **Architecture baseline:** The Orchestrator is the central workflow controller and package assembler. Retrieval occurs through MCP. Validation is completeness-only until further rules are supplied. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. Technical Architecture

Web Application  
- Auditor Portal / Grid  
- Validation / Review Portal  
- Final Approver Portal / Grid  
\|  
API / Backend -\> Orchestrator  
\|  
Query Understanding -\> Query Type Classification  
\|  
Requirement Catalog -\> Required Evidence -\> Evidence Source Registry  
\|  
Registry Resolution -\> Retrieval Planning -\> Retrieval Agent -\> MCP  
\|  
Mock APIs / SQLite Source Systems  
\|  
Retrieved Data/Documents -\> Extraction/Parsing -\> Normalization  
\|  
Canonical Evidence Model -\> Evidence Staging -\> Completeness Validation  
\|  
Orchestrator -\> Evidence Review Package -\> Request DB -\> SME  
\|  
Approve -\> Orchestrator -\> Final Response Package -\> Storage -\> Notification

# 2. Technology Baseline

| **Component**        | **Development technology / approach**                           | **Notes**                                                                                                         |
|----------------------|-----------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| Backend API          | Python + FastAPI                                                | REST API for application and workflow endpoints.                                                                  |
| Orchestration        | Python Orchestrator using LangGraph/LangChain where appropriate | Owns state transitions and agent invocation.                                                                      |
| LLM integration      | Approved enterprise LLM provider                                | Used where agentic reasoning is required; configuration-driven.                                                   |
| MCP                  | MCP gateway/layer + source-specific connectors                  | No direct Retrieval Agent access to source systems.                                                               |
| Source mocks         | SQLite + mock API layer                                         | One logical source integration per enterprise application.                                                        |
| Request DB           | SQLite                                                          | Stores request metadata, status, package references, and approval/notification state.                             |
| Evidence storage     | Local filesystem                                                | Stores staged evidence, manual uploads, review package, and final response package.                               |
| Configuration tables | SQLite tables                                                   | Requirement Catalog and Evidence Source Registry are stored in SQLite using the exact agreed stakeholder schemas. |
| Data modeling        | Pydantic models                                                 | Canonical runtime structures for requests, evidence, mappings, and validation.                                    |
| Database access      | SQLAlchemy + Alembic                                            | Useful for controlled schema evolution even with SQLite during development.                                       |
| Testing              | pytest                                                          | Unit, integration, workflow, and connector contract tests.                                                        |
| Notifications        | Gmail                                                           | Application-link notifications; provider should remain abstracted behind a notification service.                  |
| Containerization     | Docker                                                          | Repeatable development/runtime environment.                                                                       |

# 3. Agent Responsibilities

| **Component**             | **Responsibility**                                                                                          | **Does not own**                                      |
|---------------------------|-------------------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| Orchestrator              | Controls end-to-end state, invokes components, collects outputs, and builds review/final response packages. | Direct source-specific retrieval logic.               |
| Query Understanding Agent | Converts natural language into Structured Query and extracts available business parameters.                 | Determining evidence requirements or source systems.  |
| Query Type Classification | Identifies Query Type.                                                                                      | Selecting source APIs.                                |
| Retrieval Planning        | Builds source-aware plan from required evidence and registry mappings.                                      | Direct database/API access.                           |
| Retrieval Agent           | Executes retrieval plan through MCP.                                                                        | Business approval or final response decisions.        |
| MCP Layer                 | Standardized connectivity/tool interface to source connectors.                                              | Business reasoning.                                   |
| Validation Engine         | Completeness check only.                                                                                    | Advanced business-rule validation not yet configured. |

# 4. Requirement Catalog — SQLite Table Schema

| **Field**            | **Meaning**                                   |
|----------------------|-----------------------------------------------|
| Requirement ID       | Unique identifier for the requirement record. |
| Query Type           | Query Type to which the requirement applies.  |
| Evidence Type        | Standard name of the required evidence item.  |
| Evidence Description | Clarifies exactly what evidence is expected.  |

| Storage rule: Requirement Catalog and Evidence Source Registry are stored as SQLite tables only. No Excel/CSV runtime dependency is used. |
|-------------------------------------------------------------------------------------------------------------------------------------------|

# 5. Evidence Source Registry — SQLite Table Schema

| **Field**                     | **Meaning**                                                                                                            |
|-------------------------------|------------------------------------------------------------------------------------------------------------------------|
| Evidence Type                 | Evidence item for which a source mapping is defined.                                                                   |
| Source System                 | Enterprise application/system that contains or exposes the evidence.                                                   |
| Source Usage / Selection Rule | Defines how the mapped source should be used when multiple sources exist. Do not assume priority unless it is defined. |
| Retrieval Method              | How the evidence is technically obtained from the source. Current design: APIs only.                                   |
| Search / Retrieval Keys       | Identifier(s) used to locate the evidence in the source.                                                               |
| Source Object / Location      | Specific API endpoint, object, report, module, repository, or location within the source.                              |
| Expected Output Type          | Expected result format used to determine downstream processing.                                                        |

All evidence retrieval from enterprise source systems is performed through APIs only. For development, mock APIs backed by SQLite datasets are used; the integration boundary remains API-based.

# 6. Retrieval and Processing

Requirement Catalog -\> Required Evidence  
Evidence Source Registry -\> Applicable Source Mappings  
Registry Resolution -\> Retrieval Plan  
Retrieval Plan -\> Retrieval Agent -\> MCP  
MCP -\> Source-specific connector -\> Mock API -\> SQLite source data  
Source response -\> Extraction/Parsing (as required)  
-\> Normalization -\> Canonical Evidence Model -\> Evidence Staging

- The system must preserve source attribution, source reference, and retrieval provenance for every evidence item.

- Original evidence/file should be retained when available; normalized content is used for internal checks and packaging.

- One query can map to multiple source systems and multiple evidence items.

# 7. Validation and Recovery

| **Step**                    | **Behavior**                                                                             |
|-----------------------------|------------------------------------------------------------------------------------------|
| Completeness check          | Compare the required evidence set against evidence available after retrieval/processing. |
| Complete                    | Orchestrator prepares Evidence Review Package.                                           |
| Incomplete - retry possible | Send the affected retrieval back through retry/rework.                                   |
| Incomplete - manual action  | Human Validator can upload evidence manually.                                            |
| Not required / accepted     | Human Validator can mark an item as not required and continue.                           |
| Retry policy                | Maximum retries, timeout, backoff, and escalation remain configurable/open.              |

# 8. Storage and State

- Request DB (SQLite) is the system of record for request metadata and workflow state during development.

- Local filesystem is used for staged evidence and package files.

- The Orchestrator should treat in-memory values as transient workflow state, not permanent storage.

- Package locations should be stored as references/links in Request DB.

# 9. Notification

| **Event**                     | **Channel** | **Payload**                                    |
|-------------------------------|-------------|------------------------------------------------|
| Evidence Review Package ready | Gmail       | Application link to Final Approver experience. |
| Final Response Package ready  | Gmail       | Application link to Auditor experience.        |

| **Mail account:** Development notifications use Gmail account singhishant01feb@gmail.com. The mail provider should be abstracted so it can be replaced for production enterprise mail without changing workflow logic. |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

| **Document status**  | Draft for development                        |
|----------------------|----------------------------------------------|
| **Working baseline** | Updated production architecture              |
| **Scope**            | Backend + Agentic + defined Web App behavior |
| **Application**      | Audit Evidence Platform                      |

| **Primary principle:** The Orchestrator controls the end-to-end workflow. It creates the Evidence Review Package before SME approval and the Final Response Package after SME approval. |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. End-to-End Flow

AUDITOR  
- Login -\> Auditor Portal / Grid  
- Submit natural-language audit query  
\|  
WEB APPLICATION  
- Request sent to API / Backend  
\|  
API / BACKEND  
- Create Request ID  
- Persist initial request in Request DB (SQLite)  
\|  
ORCHESTRATOR  
- Controls workflow and request state  
\|  
QUERY UNDERSTANDING AGENT  
- Structured Query + business parameters  
\|  
QUERY TYPE CLASSIFICATION  
- Query Type  
\|  
REQUIREMENT CATALOG (SQLite table)  
- Required Evidence  
\|  
EVIDENCE SOURCE REGISTRY (SQLite table)  
- Source mappings + API retrieval method + keys  
\|  
REGISTRY RESOLUTION -\> RETRIEVAL PLANNING  
\|  
RETRIEVAL AGENT -\> MCP -\> SOURCE-SPECIFIC CONNECTORS  
\|  
MOCK SOURCE APIs -\> SQLITE SOURCE DATA  
- Enterprise evidence retrieval is API-only  
\|  
RETRIEVED DATA / DOCUMENTS  
- Extraction/Parsing as required  
- Normalization  
- Canonical Evidence Model  
- Evidence Staging  
\|  
VALIDATION ENGINE  
- Completeness check only  
\|  
DECISION  
- Complete -\> Review Package  
- Missing/Unclear -\> Retry / Manual Upload / Accept Not Required  
\|  
ORCHESTRATOR  
- Collect all outputs  
- Prepare Evidence Review Package  
- Update Request DB  
\|  
NOTIFICATION SERVICE -\> GMAIL -\> SME  
\|  
SME / FINAL APPROVER  
- Review package  
- Approve / Reject  
\|  
APPROVE -\> ORCHESTRATOR  
- Use only SME-approved evidence  
- Prepare Final Response Package  
- Store package in local file storage  
- Update Request DB  
- Notify Auditor via Gmail  
\|  
AUDITOR -\> Application Link -\> Final Response Package  
\|  
COMPLETED

# 2. Request State Flow

| **Stage**          | **Entry condition**                   | **Exit condition / next stage**                                     |
|--------------------|---------------------------------------|---------------------------------------------------------------------|
| Submitted          | Auditor submits request.              | Request record created -\> Processing.                              |
| Processing         | Orchestrator starts workflow.         | Required evidence retrieved/processed -\> Validation Pending.       |
| Validation Pending | Evidence is staged.                   | Complete -\> Review Ready; incomplete -\> Rework Required.          |
| Rework Required    | Missing/unclear evidence exists.      | Retry, manual upload, or accepted exception -\> Validation Pending. |
| Review Ready       | Evidence Review Package is available. | SME notified -\> SME Review.                                        |
| SME Review         | SME opens package.                    | Approve -\> Final Response; Reject -\> Rework.                      |
| Final Response     | SME approval received.                | Final package stored -\> Notification.                              |
| Notification       | Final package link available.         | Auditor notified -\> Completed.                                     |

# 3. Missing / Unclear Evidence Branch

Validation detects missing required evidence  
\|  
Human Validator / Review Portal  
\|  
+--\> Retry / Rework -\> Retrieval -\> Processing -\> Validation  
\|  
+--\> Manual Evidence Upload -\> Staging -\> Validation  
\|  
+--\> Accept Not Required -\> Continue -\> Evidence Review Package  
\|  
When complete/accepted -\> Orchestrator -\> SME Review

# 4. SME Approval Branch

Evidence Review Package ready  
\|  
SME / Final Approver  
\|  
+--\> REJECT -\> Orchestrator -\> Rework / Manual Upload -\> Revalidation  
\|  
+--\> APPROVE -\> Orchestrator -\> Final Response Package -\> Storage -\> Notify Auditor

# 5. Multi-Source Example

A single request may require evidence from multiple source applications. The source registry and retrieval plan determine the applicable mappings; the Retrieval Agent executes through MCP, and the Canonical Evidence Model preserves source attribution.

Query  
- Query Type: Payment Testing  
- Required Evidence: Invoice + PO + GRN/SES + Approval  
\|  
Registry mappings  
- Invoice -\> GROSS  
- PO -\> ARIBA  
- GRN/SES -\> GESS  
- Approval -\> IPAMS  
\|  
Retrieval Agent -\> MCP -\> each applicable connector  
\|  
Canonical Evidence Model  
- Evidence ID  
- Evidence Type  
- Source System  
- Source Reference  
- Payload / file reference  
\|  
Completeness check -\> Evidence Review Package

# 6. Package Lifecycle

| **Package**             | **Created by**                  | **Audience** | **Stored where**                          | **Approval status**  |
|-------------------------|---------------------------------|--------------|-------------------------------------------|----------------------|
| Evidence Review Package | Orchestrator                    | SME          | Local file storage + Request DB reference | Pending SME approval |
| Final Response Package  | Orchestrator after SME approval | Auditor      | Local file storage + Request DB reference | Approved             |

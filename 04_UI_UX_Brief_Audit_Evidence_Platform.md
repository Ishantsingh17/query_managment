| **Document status**  | Draft for development                        |
|----------------------|----------------------------------------------|
| **Working baseline** | Updated production architecture              |
| **Scope**            | Backend + Agentic + defined Web App behavior |
| **Application**      | Audit Evidence Platform                      |

| **UI naming rule:** Use the application name “Audit Evidence Platform” in user-facing screens. Do not expose internal development labels or unrelated organization names in the UI. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. UX Objectives

- Provide a clean, professional enterprise experience with clear hierarchy and minimal scrolling.

- Use the same web application for Auditor, Human Validator, and Final Approver roles.

- Make request status, evidence completeness, package readiness, and next action immediately visible.

- Keep detailed evidence accessible through focused panels, drawers, or tabs instead of long single-page screens.

- Make approval and rework actions explicit and auditable.

# 2. Application Shell

| **Area**       | **UI guidance**                                                                             |
|----------------|---------------------------------------------------------------------------------------------|
| Header         | Application name, current role, user identity, notification indicator, sign out.            |
| Navigation     | Compact left navigation or top navigation with role-specific destinations.                  |
| Content        | Desktop-first responsive layout using cards, tables, status chips, and side panels.         |
| Primary action | One dominant action per page (Submit Request, Upload Evidence, Approve, Reject).            |
| Feedback       | Use clear success/error/processing states; avoid technical stack details in user messaging. |

# 3. Auditor Portal / Grid

| **Screen**     | **Key elements**                                                                                 |
|----------------|--------------------------------------------------------------------------------------------------|
| Dashboard      | Request count by status, recent requests, quick action to create request.                        |
| Create Request | Natural-language request input, optional key fields if known, submit button, clear validation.   |
| Request Detail | Request ID, Query Type, status timeline, required evidence summary, package link when available. |
| Final Response | Final Response Package summary, approved evidence list, links/files, completion status.          |

# 4. Validation / Review Portal

| **Element**      | **Behavior**                                                                                                  |
|------------------|---------------------------------------------------------------------------------------------------------------|
| Request list     | Filter by request status, missing/unclear state, priority if later introduced.                                |
| Evidence summary | Required evidence list with status: Available / Missing / Manually Uploaded / Accepted Not Required.          |
| Evidence panel   | Show evidence metadata, source system, source reference, file/data preview or link.                           |
| Actions          | Retry/Rework, Manual Upload, Accept Not Required, Continue.                                                   |
| Audit trail view | Show current workflow stage and relevant system events; detailed workflow history remains a future extension. |

# 5. Final Approver (SME) Portal / Grid

| **Element**     | **Behavior**                                                                                                 |
|-----------------|--------------------------------------------------------------------------------------------------------------|
| Approval queue  | List review-ready requests with Request ID, Query Type, validation status, created date, and current status. |
| Review package  | Compact summary of request, required evidence, source systems, evidence status, and completeness result.     |
| Evidence view   | Open evidence content through preview/link without leaving the application unnecessarily.                    |
| Decision action | Approve or Reject with mandatory comment for Reject.                                                         |
| Outcome banner  | Show clear confirmation after action and current request status.                                             |

# 6. Visual Direction

- Use a restrained enterprise visual system: light background, strong navy/blue headings, neutral cards, subtle borders, and restrained status colors.

- Use consistent status chips and iconography rather than large decorative graphics.

- Prefer tables with sticky headers and compact row heights for request/evidence grids.

- Use drawers/modals for secondary details to reduce vertical scrolling.

- Keep typography simple and readable; use one primary font family with clear heading hierarchy.

# 7. Key Components

| **Component**       | **Use**                                                                                 |
|---------------------|-----------------------------------------------------------------------------------------|
| Status chip         | Workflow state such as Processing, Review Ready, Approved, Rework Required.             |
| Evidence card       | Evidence type, source, status, and access link.                                         |
| Progress stepper    | Request lifecycle: Retrieval -\> Validation -\> Review -\> Approval -\> Final Response. |
| Data grid           | Auditor, validator, and SME queues.                                                     |
| Side panel          | Detailed evidence or request information without full-page navigation.                  |
| Confirmation dialog | Approve, Reject, Manual Upload, and Accept Not Required actions.                        |

# 8. UX Content Guidelines

- Use business-friendly labels such as “Evidence Review Package”, “Final Response Package”, “Validation Status”, and “Source System”.

- Do not expose agent prompts, model names, MCP implementation details, or internal orchestration terminology to end users unless required for support diagnostics.

- For missing evidence, clearly state what is missing and what action is available.

- For errors, explain the next user action instead of showing raw exception messages.

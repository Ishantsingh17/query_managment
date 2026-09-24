"""User-facing labels. Internal codes stay in the DB; the UI only sees business-friendly names.

Query Type display names come from the `query_type_definitions` table (stakeholder configuration);
they are cached here by `app.registry.resolution.refresh_label_cache`.
Evidence labels are presentation only — which evidence is required comes from the Requirement Catalog.
"""

_QUERY_TYPE_LABELS: dict[str, str] = {}


def set_query_type_labels(labels: dict[str, str]) -> None:
    _QUERY_TYPE_LABELS.clear()
    _QUERY_TYPE_LABELS.update(labels)


EVIDENCE_LABELS: dict[str, str] = {
    "VENDOR_PAYABLE_BALANCE": "Vendor-wise Payable Balance",
    "AGEING": "Ageing",
    "SIGNED_CONFIRMATION_LETTER": "Signed Confirmation Letter",
    "APTB_LEDGER_EXTRACT": "APTB Ledger Extract",
    "VENDOR_CONTACT_DETAILS": "Vendor Contact Details",
    "INVOICE": "Invoice",
    "PO": "Purchase Order",
    "GRN_SES": "GRN / SES",
    "PAYMENT_REPORT": "Payment Report",
    "APPROVAL": "Payment Approval",
    "PAYMENT_ADVICE_UTR": "Payment Advice / UTR",
    "ACCOUNTING_ENTRY": "Accounting Entries",
    "SIGNATORY_EMAIL_APPROVAL": "Signatory Email Approval",
    "IPAMS_APPROVAL": "IPAMS Approval",
    "BOARD_RESOLUTION_LIMITS": "Board Resolution Limits",
}

# Short labels used in "missing evidence" summaries, e.g. "IPAMS Approval".
EVIDENCE_SHORT: dict[str, str] = {
    "VENDOR_PAYABLE_BALANCE": "payable balance", "AGEING": "ageing", "SIGNED_CONFIRMATION_LETTER": "confirmation letter",
    "APTB_LEDGER_EXTRACT": "APTB extract", "VENDOR_CONTACT_DETAILS": "vendor contacts", "INVOICE": "Invoice",
    "PO": "PO", "GRN_SES": "GRN/SES", "PAYMENT_REPORT": "payment report", "APPROVAL": "Approval",
    "PAYMENT_ADVICE_UTR": "UTR", "ACCOUNTING_ENTRY": "accounting entries", "SIGNATORY_EMAIL_APPROVAL": "signatory approval",
    "IPAMS_APPROVAL": "approval", "BOARD_RESOLUTION_LIMITS": "board resolution",
}

# Icon hint per evidence type, consumed by the web app.
EVIDENCE_ICONS: dict[str, str] = {
    "VENDOR_PAYABLE_BALANCE": "file", "AGEING": "file", "SIGNED_CONFIRMATION_LETTER": "stamp",
    "APTB_LEDGER_EXTRACT": "file", "VENDOR_CONTACT_DETAILS": "building", "INVOICE": "file", "PO": "cart",
    "GRN_SES": "clipboard", "PAYMENT_REPORT": "file", "APPROVAL": "stamp", "PAYMENT_ADVICE_UTR": "file",
    "ACCOUNTING_ENTRY": "file", "SIGNATORY_EMAIL_APPROVAL": "stamp", "IPAMS_APPROVAL": "stamp",
    "BOARD_RESOLUTION_LIMITS": "stamp",
}

STATUS_LABELS: dict[str, str] = {
    "REQUEST_CREATED": "Submitted",
    "PROCESSING": "Processing",
    "VALIDATION_PENDING": "Validation Pending",
    "REWORK_REQUIRED": "Rework Required",
    "REVIEW_READY": "Review Ready",
    "SME_REVIEW": "SME Review",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "FINAL_RESPONSE_READY": "Final Response Ready",
    "NOTIFIED": "Notified",
    "COMPLETED": "Completed",
}

ROLE_LABELS = {"AUDITOR": "Auditor", "VALIDATOR": "Human Validator", "SME": "Final Approver (SME)", "SYSTEM": "System"}


def query_type_label(code: str | None) -> str:
    return _QUERY_TYPE_LABELS.get(code or "", (code or "Unclassified").replace("_", " ").title())


def evidence_label(code: str) -> str:
    return EVIDENCE_LABELS.get(code, code.replace("_", " ").title())

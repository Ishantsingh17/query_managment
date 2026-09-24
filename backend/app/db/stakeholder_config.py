"""Authoritative stakeholder configuration, loaded into the SQLite configuration tables.

QUERY_TYPE_DEFINITIONS and REQUIREMENT_CATALOG come from the stakeholder mapping
(Query Type / Evidence Required / What the BOT/Agent can automate).
The automation description is Query Type behaviour/context and lives in `query_type_definitions`,
never as a Requirement Catalog column.

EVIDENCE_SOURCE_REGISTRY: the stakeholder table does not define source systems. Only these mappings are
documented (App Flow, multi-source example): Invoice -> GROSS, PO -> ARIBA, GRN/SES -> GESS, Approval -> IPAMS.
All other rows are DEVELOPMENT PLACEHOLDERS pending stakeholder confirmation — change them here (config), not in code.

Search / Retrieval Keys grammar (a documented dependency is written explicitly, never assumed by code):
    "A / B"                -> either key identifies the record
    "A, B"                 -> both keys are required
    "PO Number [from INVOICE]" -> value may be supplied in the request or taken from the retrieved INVOICE record
"""

# (query_type, display_name, evidence_required (stakeholder wording), automation_behavior (stakeholder wording),
#  classification_keywords "phrase=weight; ..." used by the deterministic classifier)
QUERY_TYPE_DEFINITIONS = [
    ("TRADE_PAYABLES_BALANCE_CONFIRMATION", "Trade Payables Balance Confirmation",
     "Vendor-wise payable balance; Ageing; Signed confirmation letter; APTB ledger extract; Vendor contact details",
     "Retrieve APTB data; Identify selected vendors; Retrieve outstanding invoices; Retrieve vendor contact details/email; "
     "Collect relevant communication; Package evidence",
     "trade payable=6; balance confirmation=4; confirmation letter=4; aptb=4; ageing=3; aging=3; payable balance=3; "
     "vendor balance=3; vendor contact=2; param:vendor_id=2"),
    ("BALANCE_CONFIRMATION_ALTERNATE_TESTING", "Balance Confirmation – Alternate Testing",
     "Invoice; PO; GRN/SES",
     "When confirmation is unavailable, retrieve invoice; Retrieve PO; Retrieve GRN/SES; "
     "Link these supporting documents for the selected outstanding item",
     "alternate testing=8; alternative testing=8; alternate procedure=6; confirmation unavailable=6; "
     "confirmation not received=6; confirmation is unavailable=6; no confirmation=5; outstanding item=3; "
     "outstanding invoice=3; param:invoice_number=2"),
    ("PAYMENT_REPORT_PAYMENT_TESTING", "Payment Report / Payment Testing",
     "Payment report; Invoice; PO; GRN/SES; Approval; Bank statement / payment advice / UTR; Accounting entries",
     "Given Payment Document Number, retrieve related invoice / PO / GRN; Retrieve approval evidence; "
     "Retrieve payment accounting; Extract UTR/payment reference; Package evidence",
     "payment testing=6; payment report=5; payment document=3; payment doc=3; utr=3; payment advice=3; "
     "accounting entr=2; three-way match=3; 3-way match=3; param:payment_document_number=1"),
    ("BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH", "Bank Portal / Payment Process Walkthrough",
     "Signatory email approval; IPAMS approval; Board Resolution limits",
     "Search designated repositories; Retrieve approval documents; Provide evidence package",
     "walkthrough=6; walk-through=6; walk through=6; bank portal=6; payment process=4; signatory=4; "
     "board resolution=5; authorisation limit=3; authorization limit=3; approval limit=3"),
]

# requirement_id, query_type, evidence_type, evidence_description  (exact 4-field schema)
REQUIREMENT_CATALOG = [
    ("REQ-001", "TRADE_PAYABLES_BALANCE_CONFIRMATION", "VENDOR_PAYABLE_BALANCE", "Vendor-wise payable balance for the selected vendor"),
    ("REQ-002", "TRADE_PAYABLES_BALANCE_CONFIRMATION", "AGEING", "Ageing of the vendor's outstanding payables"),
    ("REQ-003", "TRADE_PAYABLES_BALANCE_CONFIRMATION", "SIGNED_CONFIRMATION_LETTER", "Signed balance confirmation letter from the vendor"),
    ("REQ-004", "TRADE_PAYABLES_BALANCE_CONFIRMATION", "APTB_LEDGER_EXTRACT", "APTB ledger extract with the vendor's outstanding invoices"),
    ("REQ-005", "TRADE_PAYABLES_BALANCE_CONFIRMATION", "VENDOR_CONTACT_DETAILS", "Vendor contact details / email"),
    ("REQ-006", "BALANCE_CONFIRMATION_ALTERNATE_TESTING", "INVOICE", "Invoice for the selected outstanding item (confirmation unavailable)"),
    ("REQ-007", "BALANCE_CONFIRMATION_ALTERNATE_TESTING", "PO", "PO linked to the selected outstanding item"),
    ("REQ-008", "BALANCE_CONFIRMATION_ALTERNATE_TESTING", "GRN_SES", "GRN/SES linked to the selected outstanding item"),
    ("REQ-009", "PAYMENT_REPORT_PAYMENT_TESTING", "PAYMENT_REPORT", "Payment report for the selected payment"),
    ("REQ-010", "PAYMENT_REPORT_PAYMENT_TESTING", "INVOICE", "Invoice related to the payment document"),
    ("REQ-011", "PAYMENT_REPORT_PAYMENT_TESTING", "PO", "PO related to the payment document"),
    ("REQ-012", "PAYMENT_REPORT_PAYMENT_TESTING", "GRN_SES", "GRN/SES related to the payment document"),
    ("REQ-013", "PAYMENT_REPORT_PAYMENT_TESTING", "APPROVAL", "Payment approval evidence"),
    ("REQ-014", "PAYMENT_REPORT_PAYMENT_TESTING", "PAYMENT_ADVICE_UTR", "Bank statement / payment advice / UTR (payment reference)"),
    ("REQ-015", "PAYMENT_REPORT_PAYMENT_TESTING", "ACCOUNTING_ENTRY", "Accounting entries for the payment"),
    ("REQ-016", "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH", "SIGNATORY_EMAIL_APPROVAL", "Signatory email approval for the payment"),
    ("REQ-017", "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH", "IPAMS_APPROVAL", "IPAMS approval for the payment"),
    ("REQ-018", "BANK_PORTAL_PAYMENT_PROCESS_WALKTHROUGH", "BOARD_RESOLUTION_LIMITS", "Board Resolution limits applicable to the payment"),
]

MUST = "Must retrieve"
# evidence_type, source_system, source_usage_selection_rule, retrieval_method, search_retrieval_keys,
# source_object_location, expected_output_type  (exact 7-field schema)
EVIDENCE_SOURCE_REGISTRY = [
    # Documented mappings (App Flow multi-source example)
    ("INVOICE", "GROSS", MUST, "API", "Invoice Number / Payment Document Number", "GROSS Invoice API - GET /invoices", "PDF + Structured data"),
    ("PO", "ARIBA", MUST, "API", "PO Number [from INVOICE]", "ARIBA Purchase Order API - GET /purchase-orders", "Structured data"),
    ("GRN_SES", "GESS", MUST, "API", "PO Number [from INVOICE]", "GESS Goods Receipt / SES API - GET /goods-receipts", "PDF + Structured data"),
    ("APPROVAL", "IPAMS", MUST, "API", "Payment Document Number", "IPAMS Approval API - GET /approvals", "PDF"),
    # DEVELOPMENT PLACEHOLDERS — pending stakeholder confirmation of source systems
    ("PAYMENT_REPORT", "ORACLE", MUST, "API", "Payment Document Number", "Oracle AP API - GET /ap/payment-report", "Structured data"),
    ("PAYMENT_ADVICE_UTR", "GPS", MUST, "API", "Payment Document Number", "GPS Payment API - GET /payment-advices", "PDF + Structured data"),
    ("ACCOUNTING_ENTRY", "ORACLE", MUST, "API", "Payment Document Number", "Oracle GL API - GET /gl/journal-entries", "Structured data"),
    ("VENDOR_PAYABLE_BALANCE", "ORACLE", MUST, "API", "Vendor ID", "Oracle AP API - GET /ap/vendor-balances", "Structured data"),
    ("AGEING", "ORACLE", MUST, "API", "Vendor ID", "Oracle AP API - GET /ap/ageing", "Structured data"),
    ("APTB_LEDGER_EXTRACT", "ORACLE", MUST, "API", "Vendor ID", "Oracle AP API - GET /ap/aptb-ledger", "CSV"),
    ("VENDOR_CONTACT_DETAILS", "VMS", MUST, "API", "Vendor ID", "VMS Vendor API - GET /vendor-contacts", "Structured data"),
    ("SIGNED_CONFIRMATION_LETTER", "GRS", MUST, "API", "Vendor ID", "GRS Document Repository API - GET /balance-confirmations", "PDF"),
    ("SIGNATORY_EMAIL_APPROVAL", "GRS", MUST, "API", "Payment Document Number", "GRS Document Repository API - GET /signatory-approvals", "PDF"),
    ("IPAMS_APPROVAL", "IPAMS", MUST, "API", "Payment Document Number", "IPAMS Approval API - GET /approvals", "PDF"),
    ("BOARD_RESOLUTION_LIMITS", "GRS", MUST, "API", "Fiscal Year", "GRS Document Repository API - GET /board-resolutions", "PDF"),
]

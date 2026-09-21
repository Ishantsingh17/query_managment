"""The synthetic dataset for the four mock source databases.

Evidence is deliberately distributed across databases so the sequential
search has to traverse several sources.

THE RETRY IS STRUCTURAL, NOT SCRIPTED
-------------------------------------
For the UC-04 demo (ABC Ltd / INV-12345):

  DB-01  INVOICE, GRN            findable from the query itself
  DB-02  PURCHASE_ORDER          findable from the query itself
  DB-03  SES  (SES-455)          keyed ONLY on ses_number - every other
                                 identifier column is NULL
  DB-04  SUPPORTING_DOCUMENT     carries ses_number = SES-455

DB-03 is searched before DB-04, so on the first pass nothing in the search
context can match the SES row and it is genuinely missed. Validation returns
INCOMPLETE, the retry pass re-searches with ses_number now in context, and
DB-03 hits. That produces retry_count = 1 with no special-casing anywhere.
"""

from __future__ import annotations

DEMO_VENDOR = "ABC Ltd"
DEMO_INVOICE = "INV-12345"

# --- documents ------------------------------------------------------------
# Each entry carries: db, id, document_type, identifier, title, summary,
# plus whichever identifier columns from the schema apply.
DOCUMENTS: list[dict] = [
    # ================= UC-04 demo: ABC Ltd / INV-12345 =================
    {
        "db": "DB-01", "id": "DOC-001", "document_type": "INVOICE",
        "identifier": "INV-12345", "title": "Tax Invoice",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR,
        "invoice_number": "INV-12345", "po_number": "PO-5678", "grn_number": "GRN-999",
        "period": "August 2026", "amount": 48750.00, "currency": "OMR",
        "summary": "Vendor tax invoice for maintenance services, cross-referencing PO-5678 and GRN-999.",
    },
    {
        "db": "DB-01", "id": "DOC-002", "document_type": "GRN",
        "identifier": "GRN-999", "title": "Goods Receipt Note",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR,
        "invoice_number": "INV-12345", "po_number": "PO-5678", "grn_number": "GRN-999",
        "period": "August 2026", "amount": 48750.00, "currency": "OMR",
        "summary": "Goods receipt confirming delivery against PO-5678.",
    },
    {
        "db": "DB-02", "id": "DOC-101", "document_type": "PURCHASE_ORDER",
        "identifier": "PO-5678", "title": "Purchase Order",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR,
        "invoice_number": "INV-12345", "po_number": "PO-5678",
        "period": "August 2026", "amount": 48750.00, "currency": "OMR",
        "summary": "Approved purchase order raised on ABC Ltd for maintenance services.",
    },
    {
        # Keyed ONLY on ses_number. This is what forces the retry.
        "db": "DB-03", "id": "DOC-201", "document_type": "SES",
        "identifier": "SES-455", "title": "Service Entry Sheet",
        "ses_number": "SES-455",
        "amount": 48750.00, "currency": "OMR",
        "summary": "Service entry sheet recording service acceptance. Indexed only by SES number.",
    },
    {
        # Reveals ses_number to the search context, and is searched AFTER DB-03.
        "db": "DB-04", "id": "DOC-301", "document_type": "SUPPORTING_DOCUMENT",
        "identifier": "SUPP-01", "title": "Supporting Documentation",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR,
        "invoice_number": "INV-12345", "ses_number": "SES-455",
        "period": "August 2026",
        "summary": "Service completion certificate and acceptance correspondence referencing SES-455.",
    },

    # ---- Noise: a separate vendor chain. Must never match INV-12345. ----
    {
        "db": "DB-01", "id": "DOC-003", "document_type": "INVOICE",
        "identifier": "INV-99999", "title": "Tax Invoice",
        "vendor_id": "V002", "vendor_name": "XYZ Traders",
        "invoice_number": "INV-99999", "po_number": "PO-7777", "grn_number": "GRN-777",
        "period": "August 2026", "amount": 15200.00, "currency": "OMR",
        "summary": "Unrelated vendor invoice used to prove identifier discrimination.",
    },
    {
        "db": "DB-02", "id": "DOC-102", "document_type": "PURCHASE_ORDER",
        "identifier": "PO-7777", "title": "Purchase Order",
        "vendor_id": "V002", "vendor_name": "XYZ Traders",
        "invoice_number": "INV-99999", "po_number": "PO-7777",
        "period": "August 2026", "amount": 15200.00, "currency": "OMR",
        "summary": "Unrelated vendor purchase order.",
    },

    # ---- UC-04 permanently-missing SES scenario, ends NEEDS_REVIEW ----
    {
        "db": "DB-01", "id": "DOC-004", "document_type": "INVOICE",
        "identifier": "INV-22222", "title": "Tax Invoice",
        "vendor_id": "V003", "vendor_name": "Delta Services",
        "invoice_number": "INV-22222", "po_number": "PO-8888", "grn_number": "GRN-888",
        "period": "August 2026", "amount": 9300.00, "currency": "OMR",
        "summary": "Delta Services invoice. No service entry sheet exists in any source.",
    },
    {
        "db": "DB-01", "id": "DOC-005", "document_type": "GRN",
        "identifier": "GRN-888", "title": "Goods Receipt Note",
        "vendor_id": "V003", "vendor_name": "Delta Services",
        "invoice_number": "INV-22222", "po_number": "PO-8888", "grn_number": "GRN-888",
        "period": "August 2026",
        "summary": "Goods receipt for Delta Services delivery.",
    },
    {
        "db": "DB-02", "id": "DOC-103", "document_type": "PURCHASE_ORDER",
        "identifier": "PO-8888", "title": "Purchase Order",
        "vendor_id": "V003", "vendor_name": "Delta Services",
        "invoice_number": "INV-22222", "po_number": "PO-8888",
        "period": "August 2026",
        "summary": "Purchase order raised on Delta Services.",
    },
    {
        "db": "DB-04", "id": "DOC-302", "document_type": "SUPPORTING_DOCUMENT",
        "identifier": "SUPP-02", "title": "Supporting Documentation",
        "vendor_id": "V003", "vendor_name": "Delta Services",
        "invoice_number": "INV-22222",
        "period": "August 2026",
        "summary": "Delivery correspondence for Delta Services.",
    },

    # ================= UC-01 complete: August 2026 / SOB 101 =================
    {
        "db": "DB-01", "id": "DOC-401", "document_type": "GL_DUMP",
        "identifier": "GL-AUG26-101", "title": "General Ledger Dump",
        "sob": "101", "nac_code": "5000-5999", "period": "August 2026",
        "summary": "GL expense ledger extract for SOB 101, NAC 5000-5999, August 2026.",
    },
    {
        "db": "DB-01", "id": "DOC-402", "document_type": "TRIAL_BALANCE",
        "identifier": "TB-AUG26-101", "title": "Trial Balance",
        "sob": "101", "nac_code": "5000-5999", "period": "August 2026",
        "summary": "Trial balance for SOB 101 as at 31 August 2026.",
    },
    {
        "db": "DB-02", "id": "DOC-403", "document_type": "COST_DRILL_AP",
        "identifier": "CD-AP-AUG26", "title": "Cost Drill Report - AP",
        "sob": "101", "nac_code": "5000-5999", "period": "August 2026", "report_type": "AP",
        "summary": "Accounts payable cost drill for NAC range 5000-5999.",
    },
    {
        "db": "DB-03", "id": "DOC-404", "document_type": "COST_DRILL_AR",
        "identifier": "CD-AR-AUG26", "title": "Cost Drill Report - AR",
        "sob": "101", "nac_code": "5000-5999", "period": "August 2026", "report_type": "AR",
        "summary": "Accounts receivable cost drill for NAC range 5000-5999.",
    },
    {
        "db": "DB-03", "id": "DOC-405", "document_type": "COST_DRILL_OTHERS",
        "identifier": "CD-OTH-AUG26", "title": "Cost Drill Report - Others",
        "sob": "101", "nac_code": "5000-5999", "period": "August 2026", "report_type": "OTHERS",
        "summary": "Other cost drill categories for NAC range 5000-5999.",
    },

    # ---- UC-01 incomplete: September 2026 has no Others report (TC-02) ----
    {
        "db": "DB-01", "id": "DOC-411", "document_type": "GL_DUMP",
        "identifier": "GL-SEP26-101", "title": "General Ledger Dump",
        "sob": "101", "nac_code": "5000-5999", "period": "September 2026",
        "summary": "GL expense ledger extract for SOB 101, September 2026.",
    },
    {
        "db": "DB-01", "id": "DOC-412", "document_type": "TRIAL_BALANCE",
        "identifier": "TB-SEP26-101", "title": "Trial Balance",
        "sob": "101", "nac_code": "5000-5999", "period": "September 2026",
        "summary": "Trial balance for SOB 101 as at 30 September 2026.",
    },
    {
        "db": "DB-02", "id": "DOC-413", "document_type": "COST_DRILL_AP",
        "identifier": "CD-AP-SEP26", "title": "Cost Drill Report - AP",
        "sob": "101", "nac_code": "5000-5999", "period": "September 2026", "report_type": "AP",
        "summary": "Accounts payable cost drill for September 2026.",
    },
    {
        "db": "DB-03", "id": "DOC-414", "document_type": "COST_DRILL_AR",
        "identifier": "CD-AR-SEP26", "title": "Cost Drill Report - AR",
        "sob": "101", "nac_code": "5000-5999", "period": "September 2026", "report_type": "AR",
        "summary": "Accounts receivable cost drill for September 2026.",
    },

    # ================= UC-02: Account 4100 / June 2026 =================
    {
        "db": "DB-01", "id": "DOC-501", "document_type": "LEDGER_EXTRACT",
        "identifier": "LE-4100-JUN26", "title": "Ledger Extract",
        "account_number": "4100", "period": "June 2026", "sob": "101",
        "summary": "Account 4100 ledger extract for June 2026.",
    },
    {
        "db": "DB-02", "id": "DOC-502", "document_type": "OPENING_BALANCE",
        "identifier": "OB-4100-JUN26", "title": "Opening Balance Statement",
        "account_number": "4100", "period": "June 2026",
        "summary": "Opening balance for account 4100 as at 1 June 2026.",
    },
    {
        "db": "DB-02", "id": "DOC-503", "document_type": "MOVEMENT_DETAILS",
        "identifier": "MV-4100-JUN26", "title": "Movement, Additions and Adjustments",
        "account_number": "4100", "period": "June 2026",
        "summary": "Movement schedule with additions and adjustments for account 4100.",
    },
    {
        "db": "DB-02", "id": "DOC-504", "document_type": "CLOSING_BALANCE",
        "identifier": "CB-4100-JUN26", "title": "Closing Balance Statement",
        "account_number": "4100", "period": "June 2026",
        "summary": "Closing balance for account 4100 as at 30 June 2026.",
    },
    {
        "db": "DB-03", "id": "DOC-505", "document_type": "AGEING_REPORT",
        "identifier": "AG-4100-JUN26", "title": "Ageing Analysis",
        "account_number": "4100", "period": "June 2026",
        "summary": "Ageing buckets for account 4100 including long outstanding items.",
    },
    # LONG_OUTSTANDING_EXPLANATION is intentionally absent from every source:
    # it needs human judgement and must drive NEEDS_REVIEW (TC-04).

    # ================= UC-03: as at 30 June 2026 =================
    {
        "db": "DB-01", "id": "DOC-601", "document_type": "APTB",
        "identifier": "APTB-JUN26", "title": "Vendor-wise Payable Balances (APTB)",
        "period": "30 June 2026",
        "summary": "Accounts payable trial balance by vendor as at 30 June 2026.",
    },
    {
        "db": "DB-02", "id": "DOC-602", "document_type": "AGEING_REPORT",
        "identifier": "AG-AP-JUN26", "title": "Trade Payables Ageing Report",
        "period": "30 June 2026",
        "summary": "Trade payables ageing report as at 30 June 2026.",
    },
    {
        "db": "DB-03", "id": "DOC-603", "document_type": "BALANCE_CONFIRMATION_LETTER",
        "identifier": "BCL-V001-JUN26", "title": "Balance Confirmation Letter",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR, "period": "30 June 2026",
        "summary": "Balance confirmation letter prepared for ABC Ltd, pending signatory approval.",
    },
    {
        "db": "DB-04", "id": "DOC-604", "document_type": "VENDOR_CONTACT_DETAILS",
        "identifier": "VC-V001", "title": "Vendor Contact Details",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR, "period": "30 June 2026",
        "summary": "Registered contact and communication details for ABC Ltd.",
    },
    {
        "db": "DB-04", "id": "DOC-605", "document_type": "OUTSTANDING_INVOICE_DETAILS",
        "identifier": "OI-V001-JUN26", "title": "Outstanding Invoice Details",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR, "period": "30 June 2026",
        "summary": "Invoice-level outstanding detail for ABC Ltd as at 30 June 2026.",
    },
]


# --- transactions ---------------------------------------------------------
# Tabular corroboration. Searched to enrich the identifier context; evidence
# files themselves always come from the documents table.
TRANSACTIONS: list[dict] = [
    {
        "db": "DB-01", "id": "TXN-001", "transaction_type": "AP_INVOICE",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR, "invoice_number": "INV-12345",
        "po_number": "PO-5678", "grn_number": "GRN-999",
        "amount": 48750.00, "currency": "OMR", "period": "August 2026",
        "sob": "101", "nac_code": "5210",
    },
    {
        "db": "DB-01", "id": "TXN-002", "transaction_type": "GL_LINE",
        "sob": "101", "nac_code": "5210", "amount": 48750.00, "currency": "OMR",
        "period": "August 2026", "report_type": "AP", "account_number": "4100",
    },
    {
        "db": "DB-02", "id": "TXN-003", "transaction_type": "GL_LINE",
        "sob": "101", "nac_code": "5480", "amount": 12100.00, "currency": "OMR",
        "period": "August 2026", "report_type": "AR",
    },
    {
        "db": "DB-02", "id": "TXN-004", "transaction_type": "ACCOUNT_MOVEMENT",
        "account_number": "4100", "period": "June 2026", "amount": 205400.00,
        "currency": "OMR", "sob": "101",
    },
    {
        "db": "DB-03", "id": "TXN-005", "transaction_type": "VENDOR_BALANCE",
        "vendor_id": "V001", "vendor_name": DEMO_VENDOR, "period": "30 June 2026",
        "amount": 87310.00, "currency": "OMR",
    },
    {
        "db": "DB-04", "id": "TXN-006", "transaction_type": "VENDOR_BALANCE",
        "vendor_id": "V003", "vendor_name": "Delta Services", "period": "30 June 2026",
        "amount": 9300.00, "currency": "OMR",
    },
]


# --- document links -------------------------------------------------------
DOCUMENT_LINKS: list[dict] = [
    {"db": "DB-01", "id": "LNK-001", "source_document_id": "DOC-001",
     "related_document_id": "DOC-101", "relationship_type": "INVOICE_TO_PO"},
    {"db": "DB-01", "id": "LNK-002", "source_document_id": "DOC-001",
     "related_document_id": "DOC-002", "relationship_type": "INVOICE_TO_GRN"},
    {"db": "DB-04", "id": "LNK-003", "source_document_id": "DOC-301",
     "related_document_id": "DOC-201", "relationship_type": "SUPPORTING_TO_SES"},
]


# --- generated GL transaction lines ---------------------------------------
# UC-01's Excel extract is compiled from these rows rather than copied from a
# document. Volume matters: the point of a transaction listing is that it is
# too long to eyeball, so the demo needs a realistic number of lines spread
# across the source systems.
_GL_ACCOUNTS = ["4100", "4120", "4200", "4310", "4450", "4610"]
_GL_VENDORS = [
    ("V001", "ABC Ltd"), ("V002", "XYZ Traders"), ("V003", "Delta Services"),
    ("V004", "Gulf Supplies LLC"), ("V005", "Northern Logistics"),
    (None, None),
]
_GL_DESCRIPTIONS = [
    "Annual maintenance contract", "Spare parts consumption",
    "Facility management charges", "Freight and handling",
    "Software subscription", "Professional fees",
    "Utilities recharge", "Consumables issue", "Equipment hire",
    "Calibration services",
]
_GL_COST_CENTRES = ["CC-100", "CC-140", "CC-220", "CC-305"]


def _build_gl_lines() -> list[dict]:
    """Deterministic GL lines for the UC-01 periods.

    Seeded from a fixed sequence so every rebuild produces identical data -
    an audit demo should be reproducible.
    """
    import random

    rng = random.Random(20260901)
    rows: list[dict] = []
    databases = ["DB-01", "DB-02", "DB-03", "DB-04"]

    # (period, how many lines) - August is the complete demo period.
    plan = [("August 2026", 128), ("September 2026", 64)]

    counter = 0
    for period, count in plan:
        month = period.split()[0][:3].upper()
        for index in range(count):
            counter += 1
            vendor_id, vendor_name = _GL_VENDORS[rng.randrange(len(_GL_VENDORS))]
            report_type = ["AP", "AR", "OTHERS"][index % 3]
            rows.append(
                {
                    # Lines are spread across systems, exactly like the
                    # documents, so the extract has to aggregate all four.
                    "db": databases[index % len(databases)],
                    "id": f"TXN-GL-{month}-{counter:05d}",
                    "transaction_type": "GL_LINE",
                    "vendor_id": vendor_id,
                    "vendor_name": vendor_name,
                    "account_number": _GL_ACCOUNTS[rng.randrange(len(_GL_ACCOUNTS))],
                    "sob": "101",
                    # Inside the 5000-5999 NAC range the use case asks about.
                    "nac_code": str(rng.randrange(5000, 6000)),
                    "amount": round(rng.uniform(120.0, 96000.0), 2),
                    "currency": "OMR",
                    "period": period,
                    "report_type": report_type,
                    "description": _GL_DESCRIPTIONS[rng.randrange(len(_GL_DESCRIPTIONS))],
                    "cost_centre": _GL_COST_CENTRES[rng.randrange(len(_GL_COST_CENTRES))],
                    "posted_date": f"{rng.randrange(1, 29):02d} {period}",
                }
            )

    # A different SOB in the same period, which the extract must EXCLUDE.
    for index in range(12):
        counter += 1
        rows.append(
            {
                "db": databases[index % len(databases)],
                "id": f"TXN-GL-OTHERSOB-{counter:05d}",
                "transaction_type": "GL_LINE",
                "account_number": "4100",
                "sob": "205",
                "nac_code": str(rng.randrange(5000, 6000)),
                "amount": round(rng.uniform(500.0, 40000.0), 2),
                "currency": "OMR",
                "period": "August 2026",
                "report_type": "AP",
                "description": "Out-of-scope SOB line",
                "cost_centre": "CC-900",
                "posted_date": "15 August 2026",
            }
        )

    # And lines outside the NAC range, also to be excluded.
    for index in range(8):
        counter += 1
        rows.append(
            {
                "db": databases[index % len(databases)],
                "id": f"TXN-GL-OUTOFRANGE-{counter:05d}",
                "transaction_type": "GL_LINE",
                "account_number": "7100",
                "sob": "101",
                "nac_code": str(rng.randrange(7000, 7999)),
                "amount": round(rng.uniform(500.0, 40000.0), 2),
                "currency": "OMR",
                "period": "August 2026",
                "report_type": "OTHERS",
                "description": "Out-of-range NAC line",
                "cost_centre": "CC-901",
                "posted_date": "18 August 2026",
            }
        )

    return rows


TRANSACTIONS.extend(_build_gl_lines())

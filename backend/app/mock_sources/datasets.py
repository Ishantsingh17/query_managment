"""Representative mock datasets for the enterprise source systems (behind the mock API contract).

Payment Report / Payment Testing (key: Payment Document Number; PO/GRN via the invoice's PO — documented in the registry)
  A  1900004533  complete: payment report, invoice, PO, GRN, approval, UTR, accounting entries across
                 ORACLE, GROSS, ARIBA, GESS, IPAMS, GPS  (also scenario D — multi-source)
  B  1900004521  IPAMS approval missing -> Rework Required
  C  1900004552  GRN posted late: first lookup misses, Retry finds it
     1900004588  guided demo: ask for the document number -> GRN missing -> validator email -> Retry finds it
  E  any         source outage via POST /mock-api/_admin/sources/{SOURCE}/availability?available=false
     1900004560  invoice references PO 4500239200 that ARIBA does not hold (mismatched identifier)
Trade Payables Balance Confirmation (key: Vendor ID)
     1004821     complete (signed confirmation letter received)
     1004877     confirmation letter not received -> missing (the case for Alternate Testing)
Balance Confirmation – Alternate Testing (key: Invoice Number of the outstanding item)
     INV-2026-08560  complete (invoice, PO, SES)
     INV-2026-08533  PO 4500239200 not in ARIBA -> PO and GRN/SES missing
Bank Portal / Payment Process Walkthrough (keys: Payment Document Number, Fiscal Year)
     1900004533 + FY2026  complete
     1900004521 + FY2026  IPAMS approval missing
     FY2025               no board resolution on file
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObjectSpec:
    source: str
    path: str               # API path under the source, e.g. "/invoices"
    table: str
    ref_field: str          # column used as the source reference
    lookup_keys: tuple[str, ...]
    columns: tuple[str, ...]
    document: bool = False  # exposes GET {path}/{ref}/document (PDF)
    rows: list[dict] = field(default_factory=list, hash=False, compare=False)


def _o(source, path, table, ref, keys, columns, rows, document=False) -> ObjectSpec:
    return ObjectSpec(source, path, table, ref, tuple(keys), tuple(columns), document, rows)


SOURCE_SYSTEMS = {
    "ORACLE": "Oracle ERP (AP / GL)",
    "GRS": "GRS Document Repository",
    "VMS": "Vendor Management System",
    "GESS": "Goods & Services Entry System",
    "LMS": "LMS",
    "ARIBA": "SAP Ariba Procurement",
    "GPS": "Global Payment System",
    "GROSS": "Invoice Processing (GROSS)",
    "IPAMS": "Integrated Payment Approval",
}

OBJECTS: list[ObjectSpec] = [
    # ---- GROSS: invoices ----
    _o("GROSS", "/invoices", "gross_invoices", "invoice_number", ["payment_document_number", "invoice_number"],
       ["invoice_number", "payment_document_number", "vendor_id", "vendor_name", "po_number", "invoice_date",
        "amount", "currency", "status", "pages", "file_size_kb"],
       [
           dict(invoice_number="INV-2026-08412", payment_document_number="1900004521", vendor_id="1004821",
                vendor_name="Northwind Industrial Supplies", po_number="4500238891", invoice_date="2026-08-04",
                amount=48500.00, currency="USD", status="Paid", pages=2, file_size_kb=184),
           dict(invoice_number="INV-2026-08455", payment_document_number="1900004533", vendor_id="1004877",
                vendor_name="Apex Logistics Ltd", po_number="4500239012", invoice_date="2026-08-06",
                amount=12240.50, currency="USD", status="Paid", pages=1, file_size_kb=142),
           dict(invoice_number="INV-2026-08501", payment_document_number="1900004552", vendor_id="1004821",
                vendor_name="Northwind Industrial Supplies", po_number="4500239177", invoice_date="2026-08-11",
                amount=7300.00, currency="USD", status="Paid", pages=1, file_size_kb=121),
           dict(invoice_number="INV-2026-08520", payment_document_number="1900004560", vendor_id="1004877",
                vendor_name="Apex Logistics Ltd", po_number="4500239200", invoice_date="2026-08-13",
                amount=9950.00, currency="USD", status="Paid", pages=1, file_size_kb=133),
           # Guided demo (ask -> missing -> retry): only the GRN posts late
           dict(invoice_number="INV-2026-08588", payment_document_number="1900004588", vendor_id="1004877",
                vendor_name="Apex Logistics Ltd", po_number="4500239288", invoice_date="2026-08-25",
                amount=18650.00, currency="USD", status="Paid", pages=2, file_size_kb=168),
           # Outstanding (unpaid) items used by balance confirmation / alternate testing
           dict(invoice_number="INV-2026-08533", payment_document_number=None, vendor_id="1004877",
                vendor_name="Apex Logistics Ltd", po_number="4500239200", invoice_date="2026-08-14",
                amount=6400.00, currency="USD", status="Outstanding", pages=1, file_size_kb=128),
           dict(invoice_number="INV-2026-08560", payment_document_number=None, vendor_id="1004877",
                vendor_name="Apex Logistics Ltd", po_number="4500239240", invoice_date="2026-08-20",
                amount=15800.00, currency="USD", status="Outstanding", pages=2, file_size_kb=176),
           dict(invoice_number="INV-2026-08577", payment_document_number=None, vendor_id="1004821",
                vendor_name="Northwind Industrial Supplies", po_number="4500239255", invoice_date="2026-08-24",
                amount=21300.00, currency="USD", status="Outstanding", pages=1, file_size_kb=139),
       ], document=True),
    # ---- ARIBA: purchase orders ----
    _o("ARIBA", "/purchase-orders", "ariba_purchase_orders", "po_number", ["po_number"],
       ["po_number", "vendor_id", "revision", "amount", "currency", "status", "created_date"],
       [
           dict(po_number="4500238891", vendor_id="1004821", revision="Rev 03", amount=48500.00, currency="USD", status="Released", created_date="2026-07-12"),
           dict(po_number="4500239012", vendor_id="1004877", revision="Rev 01", amount=12240.50, currency="USD", status="Released", created_date="2026-07-20"),
           dict(po_number="4500239177", vendor_id="1004821", revision="Rev 01", amount=7300.00, currency="USD", status="Released", created_date="2026-07-29"),
           dict(po_number="4500239240", vendor_id="1004877", revision="Rev 02", amount=15800.00, currency="USD", status="Released", created_date="2026-08-02"),
           dict(po_number="4500239255", vendor_id="1004821", revision="Rev 01", amount=21300.00, currency="USD", status="Released", created_date="2026-08-05"),
           dict(po_number="4500239288", vendor_id="1004877", revision="Rev 01", amount=18650.00, currency="USD", status="Released", created_date="2026-08-08"),
       ]),
    # ---- GESS: goods receipts / service entry sheets ----
    _o("GESS", "/goods-receipts", "gess_goods_receipts", "document_number", ["po_number"],
       ["document_number", "document_kind", "po_number", "quantity", "received_date", "received_by", "pages",
        "file_size_kb", "visible_after_calls"],
       [
           dict(document_number="GRN-88102317", document_kind="GRN", po_number="4500238891", quantity=500, received_date="2026-08-02",
                received_by="Warehouse 04", pages=1, file_size_kb=96, visible_after_calls=0),
           dict(document_number="GRN-88102401", document_kind="GRN", po_number="4500239012", quantity=120, received_date="2026-08-05",
                received_by="Warehouse 02", pages=1, file_size_kb=88, visible_after_calls=0),
           # Scenario C: posted late — first lookup misses, later lookups succeed (retry/rework)
           dict(document_number="GRN-88102519", document_kind="GRN", po_number="4500239177", quantity=73, received_date="2026-08-10",
                received_by="Warehouse 04", pages=1, file_size_kb=90, visible_after_calls=1),
           dict(document_number="SES-77100231", document_kind="SES", po_number="4500239240", quantity=1, received_date="2026-08-18",
                received_by="Facilities", pages=1, file_size_kb=84, visible_after_calls=0),
           dict(document_number="GRN-88102601", document_kind="GRN", po_number="4500239255", quantity=210, received_date="2026-08-22",
                received_by="Warehouse 01", pages=1, file_size_kb=92, visible_after_calls=0),
           # Guided demo: posted late — missing on the first lookup, found on Retry
           dict(document_number="GRN-88102688", document_kind="GRN", po_number="4500239288", quantity=150, received_date="2026-08-24",
                received_by="Warehouse 02", pages=1, file_size_kb=94, visible_after_calls=1),
       ], document=True),
    # ---- IPAMS: payment approvals ----
    _o("IPAMS", "/approvals", "ipams_approvals", "approval_ref", ["payment_document_number"],
       ["approval_ref", "payment_document_number", "approver", "approved_at", "approval_limit", "pages", "file_size_kb"],
       [
           # Scenario B: no approval for 1900004521
           dict(approval_ref="APR-771260", payment_document_number="1900004533", approver="R. Iyer (Finance Controller)",
                approved_at="2026-08-15T10:22:00", approval_limit=50000, pages=1, file_size_kb=64),
           dict(approval_ref="APR-771301", payment_document_number="1900004552", approver="M. Chen (AP Manager)",
                approved_at="2026-08-19T09:41:00", approval_limit=10000, pages=1, file_size_kb=59),
           dict(approval_ref="APR-771322", payment_document_number="1900004560", approver="M. Chen (AP Manager)",
                approved_at="2026-08-20T11:12:00", approval_limit=10000, pages=1, file_size_kb=60),
           dict(approval_ref="APR-771388", payment_document_number="1900004588", approver="R. Iyer (Finance Controller)",
                approved_at="2026-08-26T10:05:00", approval_limit=50000, pages=1, file_size_kb=63),
       ], document=True),
    # ---- ORACLE: AP / GL ----
    _o("ORACLE", "/ap/payment-report", "oracle_payment_report", "report_ref", ["payment_document_number"],
       ["report_ref", "payment_document_number", "payment_run_id", "vendor_id", "amount", "currency", "payment_date", "payment_method"],
       [
           dict(report_ref="PR-2026-08-0153", payment_document_number="1900004533", payment_run_id="PRUN-0819-A",
                vendor_id="1004877", amount=12240.50, currency="USD", payment_date="2026-08-19", payment_method="Bank transfer"),
           dict(report_ref="PR-2026-08-0148", payment_document_number="1900004521", payment_run_id="PRUN-0818-B",
                vendor_id="1004821", amount=48500.00, currency="USD", payment_date="2026-08-18", payment_method="Bank transfer"),
           dict(report_ref="PR-2026-08-0161", payment_document_number="1900004552", payment_run_id="PRUN-0821-A",
                vendor_id="1004821", amount=7300.00, currency="USD", payment_date="2026-08-21", payment_method="Bank transfer"),
           dict(report_ref="PR-2026-08-0166", payment_document_number="1900004560", payment_run_id="PRUN-0822-A",
                vendor_id="1004877", amount=9950.00, currency="USD", payment_date="2026-08-22", payment_method="Bank transfer"),
           dict(report_ref="PR-2026-08-0181", payment_document_number="1900004588", payment_run_id="PRUN-0827-A",
                vendor_id="1004877", amount=18650.00, currency="USD", payment_date="2026-08-27", payment_method="Bank transfer"),
       ]),
    _o("ORACLE", "/gl/journal-entries", "oracle_journal_entries", "je_line_ref", ["payment_document_number"],
       ["je_line_ref", "journal_id", "payment_document_number", "account", "debit", "credit", "currency", "posting_date"],
       [
           dict(je_line_ref="JE-5530981-1", journal_id="JE-5530981", payment_document_number="1900004533", account="210100 Trade Payables",
                debit=12240.50, credit=0.0, currency="USD", posting_date="2026-08-19"),
           dict(je_line_ref="JE-5530981-2", journal_id="JE-5530981", payment_document_number="1900004533", account="110200 Bank - Operating",
                debit=0.0, credit=12240.50, currency="USD", posting_date="2026-08-19"),
           dict(je_line_ref="JE-5530874-1", journal_id="JE-5530874", payment_document_number="1900004521", account="210100 Trade Payables",
                debit=48500.00, credit=0.0, currency="USD", posting_date="2026-08-18"),
           dict(je_line_ref="JE-5530874-2", journal_id="JE-5530874", payment_document_number="1900004521", account="110200 Bank - Operating",
                debit=0.0, credit=48500.00, currency="USD", posting_date="2026-08-18"),
           dict(je_line_ref="JE-5531102-1", journal_id="JE-5531102", payment_document_number="1900004552", account="210100 Trade Payables",
                debit=7300.00, credit=0.0, currency="USD", posting_date="2026-08-21"),
           dict(je_line_ref="JE-5531102-2", journal_id="JE-5531102", payment_document_number="1900004552", account="110200 Bank - Operating",
                debit=0.0, credit=7300.00, currency="USD", posting_date="2026-08-21"),
           dict(je_line_ref="JE-5531160-1", journal_id="JE-5531160", payment_document_number="1900004560", account="210100 Trade Payables",
                debit=9950.00, credit=0.0, currency="USD", posting_date="2026-08-22"),
           dict(je_line_ref="JE-5531244-1", journal_id="JE-5531244", payment_document_number="1900004588", account="210100 Trade Payables",
                debit=18650.00, credit=0.0, currency="USD", posting_date="2026-08-27"),
           dict(je_line_ref="JE-5531244-2", journal_id="JE-5531244", payment_document_number="1900004588", account="110200 Bank - Operating",
                debit=0.0, credit=18650.00, currency="USD", posting_date="2026-08-27"),
       ]),
    _o("ORACLE", "/ap/vendor-balances", "oracle_vendor_balances", "balance_ref", ["vendor_id"],
       ["balance_ref", "vendor_id", "vendor_name", "as_of_date", "outstanding_balance", "currency", "open_invoice_count"],
       [
           dict(balance_ref="VB-1004821-202608", vendor_id="1004821", vendor_name="Northwind Industrial Supplies",
                as_of_date="2026-08-31", outstanding_balance=21300.00, currency="USD", open_invoice_count=1),
           dict(balance_ref="VB-1004877-202608", vendor_id="1004877", vendor_name="Apex Logistics Ltd",
                as_of_date="2026-08-31", outstanding_balance=22200.00, currency="USD", open_invoice_count=2),
       ]),
    _o("ORACLE", "/ap/ageing", "oracle_ageing", "ageing_ref", ["vendor_id"],
       ["ageing_ref", "vendor_id", "as_of_date", "bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_over_90", "currency"],
       [
           dict(ageing_ref="AG-1004821-202608", vendor_id="1004821", as_of_date="2026-08-31", bucket_0_30=21300.00,
                bucket_31_60=0.0, bucket_61_90=0.0, bucket_over_90=0.0, currency="USD"),
           dict(ageing_ref="AG-1004877-202608", vendor_id="1004877", as_of_date="2026-08-31", bucket_0_30=15800.00,
                bucket_31_60=6400.00, bucket_61_90=0.0, bucket_over_90=0.0, currency="USD"),
       ]),
    _o("ORACLE", "/ap/aptb-ledger", "oracle_aptb_ledger", "aptb_line_ref", ["vendor_id"],
       ["aptb_line_ref", "vendor_id", "invoice_number", "invoice_date", "due_date", "amount_outstanding", "currency"],
       [
           dict(aptb_line_ref="APTB-1004821-01", vendor_id="1004821", invoice_number="INV-2026-08577", invoice_date="2026-08-24",
                due_date="2026-09-23", amount_outstanding=21300.00, currency="USD"),
           dict(aptb_line_ref="APTB-1004877-01", vendor_id="1004877", invoice_number="INV-2026-08533", invoice_date="2026-08-14",
                due_date="2026-09-13", amount_outstanding=6400.00, currency="USD"),
           dict(aptb_line_ref="APTB-1004877-02", vendor_id="1004877", invoice_number="INV-2026-08560", invoice_date="2026-08-20",
                due_date="2026-09-19", amount_outstanding=15800.00, currency="USD"),
       ]),
    # ---- VMS: vendor contacts ----
    _o("VMS", "/vendor-contacts", "vms_vendor_contacts", "contact_ref", ["vendor_id"],
       ["contact_ref", "vendor_id", "vendor_name", "contact_name", "email", "phone"],
       [
           dict(contact_ref="VC-1004821-AR", vendor_id="1004821", vendor_name="Northwind Industrial Supplies",
                contact_name="Dana Whitfield (Accounts Receivable)", email="ar@northwind.example", phone="+1 555 0101"),
           dict(contact_ref="VC-1004877-AR", vendor_id="1004877", vendor_name="Apex Logistics Ltd",
                contact_name="Marco Silva (Finance)", email="finance@apexlogistics.example", phone="+1 555 0177"),
       ]),
    # ---- GRS: document repository ----
    _o("GRS", "/balance-confirmations", "grs_balance_confirmations", "confirmation_ref", ["vendor_id"],
       ["confirmation_ref", "vendor_id", "as_of_date", "confirmed_balance", "currency", "signed_by", "received_on",
        "pages", "file_size_kb"],
       [
           # 1004877 has not returned its confirmation -> alternate testing applies
           dict(confirmation_ref="BC-2026-1004821", vendor_id="1004821", as_of_date="2026-08-31", confirmed_balance=21300.00,
                currency="USD", signed_by="Dana Whitfield", received_on="2026-09-08", pages=1, file_size_kb=212),
       ], document=True),
    _o("GRS", "/signatory-approvals", "grs_signatory_approvals", "approval_ref", ["payment_document_number"],
       ["approval_ref", "payment_document_number", "signatory", "channel", "approved_at", "pages", "file_size_kb"],
       [
           dict(approval_ref="SIG-2026-0533", payment_document_number="1900004533", signatory="A. Rao (Authorised Signatory)",
                channel="Email", approved_at="2026-08-19T08:55:00", pages=1, file_size_kb=48),
           dict(approval_ref="SIG-2026-0521", payment_document_number="1900004521", signatory="A. Rao (Authorised Signatory)",
                channel="Email", approved_at="2026-08-18T09:05:00", pages=1, file_size_kb=47),
       ], document=True),
    _o("GRS", "/board-resolutions", "grs_board_resolutions", "resolution_ref", ["fiscal_year"],
       ["resolution_ref", "fiscal_year", "resolution_date", "signatory_limits", "pages", "file_size_kb"],
       [
           dict(resolution_ref="BR-2026-014", fiscal_year="2026", resolution_date="2026-04-02",
                signatory_limits="Single signatory up to USD 50,000; dual signatory above USD 50,000", pages=3, file_size_kb=310),
       ], document=True),
    # ---- GPS: payment advice / UTR ----
    _o("GPS", "/payment-advices", "gps_payment_advices", "advice_ref", ["payment_document_number"],
       ["advice_ref", "payment_document_number", "utr", "bank", "value_date", "amount", "currency", "pages", "file_size_kb"],
       [
           dict(advice_ref="PA-2026-0819-044", payment_document_number="1900004533", utr="HDFCR52026081912345",
                bank="HDFC Bank", value_date="2026-08-19", amount=12240.50, currency="USD", pages=1, file_size_kb=57),
           dict(advice_ref="PA-2026-0818-031", payment_document_number="1900004521", utr="HDFCR52026081898765",
                bank="HDFC Bank", value_date="2026-08-18", amount=48500.00, currency="USD", pages=1, file_size_kb=56),
           dict(advice_ref="PA-2026-0821-052", payment_document_number="1900004552", utr="HDFCR52026082155501",
                bank="HDFC Bank", value_date="2026-08-21", amount=7300.00, currency="USD", pages=1, file_size_kb=55),
           dict(advice_ref="PA-2026-0822-058", payment_document_number="1900004560", utr="HDFCR52026082266610",
                bank="HDFC Bank", value_date="2026-08-22", amount=9950.00, currency="USD", pages=1, file_size_kb=55),
           dict(advice_ref="PA-2026-0827-071", payment_document_number="1900004588", utr="HDFCR52026082771234",
                bank="HDFC Bank", value_date="2026-08-27", amount=18650.00, currency="USD", pages=1, file_size_kb=56),
       ], document=True),
]


def find_spec(source: str, path: str) -> ObjectSpec | None:
    path = "/" + path.strip("/")
    for spec in OBJECTS:
        if spec.source == source.upper() and spec.path == path:
            return spec
    return None

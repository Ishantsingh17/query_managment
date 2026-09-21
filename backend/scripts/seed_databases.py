"""Build the four mock source databases and their document files.

Run:  python scripts/seed_databases.py [--force]

Idempotent: existing database files are replaced, and document files are
rewritten in place. Nothing outside databases/ and mock_documents/ is touched.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _mock_data import DOCUMENT_LINKS, DOCUMENTS, TRANSACTIONS  # noqa: E402
from _mock_docs import write_document  # noqa: E402

from app.catalog.loader import load_databases  # noqa: E402
from app.config import get_settings  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    document_type   TEXT NOT NULL,
    vendor_id       TEXT,
    vendor_name     TEXT,
    invoice_number  TEXT,
    po_number       TEXT,
    grn_number      TEXT,
    ses_number      TEXT,
    account_number  TEXT,
    sob             TEXT,
    nac_code        TEXT,
    period          TEXT,
    report_type     TEXT,
    file_path       TEXT,
    content_summary TEXT,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id               TEXT PRIMARY KEY,
    transaction_type TEXT,
    vendor_id        TEXT,
    vendor_name      TEXT,
    invoice_number   TEXT,
    po_number        TEXT,
    grn_number       TEXT,
    ses_number       TEXT,
    account_number   TEXT,
    sob              TEXT,
    nac_code         TEXT,
    amount           REAL,
    currency         TEXT,
    period           TEXT,
    report_type      TEXT,
    attributes_json  TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_links (
    id                  TEXT PRIMARY KEY,
    source_document_id  TEXT NOT NULL,
    related_document_id TEXT NOT NULL,
    relationship_type   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_invoice     ON documents(invoice_number);
CREATE INDEX IF NOT EXISTS idx_documents_vendor_id   ON documents(vendor_id);
CREATE INDEX IF NOT EXISTS idx_documents_vendor_name ON documents(vendor_name);
CREATE INDEX IF NOT EXISTS idx_documents_po          ON documents(po_number);
CREATE INDEX IF NOT EXISTS idx_documents_grn         ON documents(grn_number);
CREATE INDEX IF NOT EXISTS idx_documents_ses         ON documents(ses_number);
CREATE INDEX IF NOT EXISTS idx_documents_type        ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_txn_invoice           ON transactions(invoice_number);
CREATE INDEX IF NOT EXISTS idx_txn_vendor_id         ON transactions(vendor_id);
CREATE INDEX IF NOT EXISTS idx_txn_account           ON transactions(account_number);
CREATE INDEX IF NOT EXISTS idx_txn_scope             ON transactions(period, sob, report_type);
"""

DOC_COLUMNS = (
    "id", "document_type", "vendor_id", "vendor_name", "invoice_number",
    "po_number", "grn_number", "ses_number", "account_number", "sob",
    "nac_code", "period", "report_type", "file_path", "content_summary",
    "metadata_json", "created_at",
)
TXN_COLUMNS = (
    "id", "transaction_type", "vendor_id", "vendor_name", "invoice_number",
    "po_number", "grn_number", "ses_number", "account_number", "sob",
    "nac_code", "amount", "currency", "period", "report_type",
    "attributes_json", "created_at",
)

# Fields consumed by the seeder itself rather than stored as columns.
_META_ONLY = {"db", "identifier", "title", "summary", "amount", "currency"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _document_fields(entry: dict) -> list[tuple[str, str]]:
    """Human-readable field list rendered onto the mock document page."""
    ordered = [
        ("Document Type", entry["document_type"].replace("_", " ").title()),
        ("Identifier", entry["identifier"]),
        ("Vendor", entry.get("vendor_name")),
        ("Vendor ID", entry.get("vendor_id")),
        ("Invoice Number", entry.get("invoice_number")),
        ("PO Number", entry.get("po_number")),
        ("GRN Number", entry.get("grn_number")),
        ("SES Number", entry.get("ses_number")),
        ("Account", entry.get("account_number")),
        ("Set of Books", entry.get("sob")),
        ("NAC Code", entry.get("nac_code")),
        ("Period", entry.get("period")),
        ("Report Type", entry.get("report_type")),
    ]
    if entry.get("amount") is not None:
        ordered.append(
            ("Amount", f"{entry['amount']:,.2f} {entry.get('currency', '')}".strip())
        )
    ordered.append(("Source System", entry["db"]))
    return [(label, value) for label, value in ordered if value not in (None, "")]


def seed() -> dict[str, dict[str, int]]:
    settings = get_settings()
    settings.ensure_directories()
    root = settings.data_root

    registry = {spec.database_id: spec for spec in load_databases()}
    unknown = {entry["db"] for entry in DOCUMENTS + TRANSACTIONS} - set(registry)
    if unknown:
        raise ValueError(f"Dataset references databases absent from the registry: {sorted(unknown)}")

    # Fresh files so re-seeding is deterministic.
    connections: dict[str, sqlite3.Connection] = {}
    for database_id, spec in registry.items():
        path = spec.resolved_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        conn = sqlite3.connect(path)
        conn.executescript(SCHEMA)
        connections[database_id] = conn

    counts = {db_id: {"documents": 0, "transactions": 0, "links": 0} for db_id in registry}
    created_at = _now()

    for entry in DOCUMENTS:
        database_id = entry["db"]
        relative_path = write_document(
            root=root,
            document_type=entry["document_type"],
            identifier=entry["identifier"],
            title=entry["title"],
            fields=_document_fields(entry),
            note=entry["summary"],
        )
        metadata = {
            "identifier": entry["identifier"],
            "title": entry["title"],
            "source_database_id": database_id,
        }
        for key, value in entry.items():
            if key not in _META_ONLY and key not in DOC_COLUMNS:
                metadata[key] = value
        if entry.get("amount") is not None:
            metadata["amount"] = entry["amount"]
            metadata["currency"] = entry.get("currency")

        row = {column: entry.get(column) for column in DOC_COLUMNS}
        row["id"] = entry["id"]
        row["document_type"] = entry["document_type"]
        row["file_path"] = relative_path
        row["content_summary"] = entry["summary"]
        row["metadata_json"] = json.dumps(metadata)
        row["created_at"] = created_at

        placeholders = ", ".join("?" for _ in DOC_COLUMNS)
        connections[database_id].execute(
            f"INSERT INTO documents ({', '.join(DOC_COLUMNS)}) VALUES ({placeholders})",
            [row[column] for column in DOC_COLUMNS],
        )
        counts[database_id]["documents"] += 1

    for entry in TRANSACTIONS:
        database_id = entry["db"]
        row = {column: entry.get(column) for column in TXN_COLUMNS}
        row["id"] = entry["id"]
        row["attributes_json"] = json.dumps(
            {k: v for k, v in entry.items() if k not in TXN_COLUMNS and k != "db"}
        )
        row["created_at"] = created_at
        placeholders = ", ".join("?" for _ in TXN_COLUMNS)
        connections[database_id].execute(
            f"INSERT INTO transactions ({', '.join(TXN_COLUMNS)}) VALUES ({placeholders})",
            [row[column] for column in TXN_COLUMNS],
        )
        counts[database_id]["transactions"] += 1

    for entry in DOCUMENT_LINKS:
        database_id = entry["db"]
        connections[database_id].execute(
            "INSERT INTO document_links (id, source_document_id, related_document_id, relationship_type)"
            " VALUES (?, ?, ?, ?)",
            (
                entry["id"],
                entry["source_document_id"],
                entry["related_document_id"],
                entry["relationship_type"],
            ),
        )
        counts[database_id]["links"] += 1

    for conn in connections.values():
        conn.commit()
        conn.close()

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the mock source databases.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Accepted for symmetry; seeding always rebuilds the mock databases.",
    )
    parser.parse_args()

    counts = seed()
    settings = get_settings()

    print("Seeded mock source databases:")
    total_docs = 0
    for database_id in sorted(counts):
        stats = counts[database_id]
        total_docs += stats["documents"]
        print(
            f"  {database_id}  documents={stats['documents']:>2}"
            f"  transactions={stats['transactions']:>2}  links={stats['links']:>2}"
        )
    print(f"\n  {total_docs} documents written under {settings.mock_documents_dir.name}/")
    print(f"  databases under {settings.databases_dir.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

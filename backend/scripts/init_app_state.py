"""Create app_state.sqlite with its schema, indexes and id counter.

Run:  python scripts/init_app_state.py
Idempotent - existing data is preserved.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.services.db import connect, initialize  # noqa: E402


def main() -> int:
    settings = get_settings()
    settings.ensure_directories()
    initialize()

    conn = connect()
    try:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        counter = conn.execute(
            "SELECT value FROM id_counter WHERE name='audit_request'"
        ).fetchone()
    finally:
        conn.close()

    print(f"Application state ready at {settings.app_state_db_path.name}")
    print(f"  tables: {', '.join(tables)}")
    print(f"  next request id: {settings.request_id_prefix}{counter['value'] + 1:05d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

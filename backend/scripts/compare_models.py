"""Compare Groq models on the query-classification task.

Usage: GROQ_MODEL=<id> python scripts/compare_models.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from app.agents.query_understanding import understand  # noqa: E402

CASES = [
    ("UC-01", "Provide AP Cost Drill for August 2026, SOB 101, NAC 5000-5999."),
    ("UC-01", "Expense drill for Aug 2026, SOB 101, NAC range 5000 to 5999, report type AP"),
    ("UC-02", "Prepare schedules for account 4100 for June 2026."),
    ("UC-02", "I need the ledger extract and ageing for account 4100, June 2026."),
    ("UC-03", "Prepare trade payables ageing schedule as at 30 June 2026."),
    ("UC-03", "Balance confirmation samples for vendor ABC Ltd as at 30 June 2026."),
    ("UC-04", "Provide alternate testing documents for ABC Ltd, Invoice INV-12345."),
    ("UC-04", "Give me the invoice, PO and GRN for Delta Services invoice INV-22222."),
    ("UNSUPPORTED", "What is the weather in Muscat today?"),
    ("UNSUPPORTED", "Please prepare the statutory audit report and give your opinion."),
]


def main() -> int:
    model = os.environ.get("GROQ_MODEL", "(from .env)")
    hits = 0
    fell_back = 0

    for expected, query in CASES:
        env = understand(query)
        got = env.parsed.use_case_id
        ok = got == expected
        hits += ok
        if env.parse_source != "GROQ":
            fell_back += 1
        print(
            f"  {'ok  ' if ok else 'MISS'} [{'groq' if env.parse_source == 'GROQ' else 'RULE'}]"
            f" {got:<12} exp {expected:<12} {query[:48]}"
        )

    print(f"\n  {model}: {hits}/{len(CASES)} correct, {fell_back} fell back to rules")
    return 0 if hits == len(CASES) and fell_back == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Stable presentation ordering for evidence."""

from __future__ import annotations

from typing import Any


def order_by_checklist(
    items: list[dict[str, Any]], required: list[str], key: str = "document_type"
) -> list[dict[str, Any]]:
    """Sort evidence into the requirement catalog's order.

    Retrieval order depends on which database happened to answer first, and on
    which pass found the item, so presenting evidence that way would shuffle
    rows between runs. The checklist order is stable and is what a reviewer
    expects to read.
    """
    position = {code: index for index, code in enumerate(required)}
    return sorted(
        items,
        key=lambda item: (position.get(item.get(key), len(position)), item.get(key) or ""),
    )

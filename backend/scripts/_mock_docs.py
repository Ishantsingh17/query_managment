"""Mock document file generation.

Produces small but real PDFs so the UI's "View" action opens an actual
document. Falls back to plain text if reportlab is unavailable.
"""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - exercised by environment, not tests
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    _HAVE_REPORTLAB = True
except Exception:  # pragma: no cover
    _HAVE_REPORTLAB = False


FOLDER_BY_TYPE = {
    "INVOICE": "invoices",
    "PURCHASE_ORDER": "purchase_orders",
    "GRN": "grns",
    "SES": "ses",
    "SUPPORTING_DOCUMENT": "supporting",
    "BALANCE_CONFIRMATION_LETTER": "confirmations",
}
DEFAULT_FOLDER = "reports"


def folder_for(document_type: str) -> str:
    return FOLDER_BY_TYPE.get(document_type, DEFAULT_FOLDER)


def _write_pdf(path: Path, title: str, subtitle: str, fields: list[tuple[str, str]], note: str) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, y, title)
    y -= 8 * mm

    pdf.setFont("Helvetica", 10)
    pdf.setFillColorRGB(0.39, 0.45, 0.55)
    pdf.drawString(20 * mm, y, subtitle)
    pdf.setFillColorRGB(0, 0, 0)
    y -= 4 * mm

    pdf.setStrokeColorRGB(0.85, 0.88, 0.92)
    pdf.line(20 * mm, y, width - 20 * mm, y)
    y -= 10 * mm

    for label, value in fields:
        pdf.setFont("Helvetica", 10)
        pdf.setFillColorRGB(0.39, 0.45, 0.55)
        pdf.drawString(20 * mm, y, f"{label}")
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(75 * mm, y, str(value))
        y -= 7 * mm

    y -= 5 * mm
    pdf.setFont("Helvetica-Oblique", 9)
    pdf.setFillColorRGB(0.39, 0.45, 0.55)
    for line in _wrap(note, 95):
        pdf.drawString(20 * mm, y, line)
        y -= 5 * mm

    y -= 8 * mm
    pdf.setFont("Helvetica", 8)
    pdf.drawString(
        20 * mm, y, "SYNTHETIC MOCK DATA - Automated Audit Evidence Retrieval POC. Not real audit evidence."
    )
    pdf.showPage()
    pdf.save()


def _write_txt(path: Path, title: str, subtitle: str, fields: list[tuple[str, str]], note: str) -> None:
    lines = [title, subtitle, "-" * len(title), ""]
    lines += [f"{label:<28}{value}" for label, value in fields]
    lines += ["", *_wrap(note, 95), "", "SYNTHETIC MOCK DATA - POC only. Not real audit evidence."]
    path.write_text("\n".join(lines), encoding="utf-8")


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def write_document(
    root: Path,
    document_type: str,
    identifier: str,
    title: str,
    fields: list[tuple[str, str]],
    note: str,
) -> str:
    """Write one mock document and return its path relative to the data root."""
    folder = folder_for(document_type)
    directory = root / "mock_documents" / folder
    directory.mkdir(parents=True, exist_ok=True)

    stem = identifier.replace("/", "-").replace(" ", "_")
    subtitle = f"{document_type.replace('_', ' ').title()} - {identifier}"

    if _HAVE_REPORTLAB:
        path = directory / f"{stem}.pdf"
        _write_pdf(path, title, subtitle, fields, note)
    else:
        path = directory / f"{stem}.txt"
        _write_txt(path, title, subtitle, fields, note)

    return f"mock_documents/{folder}/{path.name}"

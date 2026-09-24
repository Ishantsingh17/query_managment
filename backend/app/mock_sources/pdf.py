"""Tiny dependency-free PDF writer used to render mock source documents."""


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_pdf(title: str, subtitle: str, fields: list[tuple[str, str]], footer: str = "") -> bytes:
    lines = [
        "BT /F2 18 Tf 56 770 Td (" + _esc(title) + ") Tj ET",
        "BT /F1 11 Tf 56 748 Td (" + _esc(subtitle) + ") Tj ET",
        "0.85 0.87 0.9 RG 56 734 m 540 734 l S",
    ]
    y = 708
    for label, value in fields:
        lines.append(f"BT /F2 10 Tf 56 {y} Td (" + _esc(label) + ") Tj ET")
        lines.append(f"BT /F1 10 Tf 220 {y} Td (" + _esc(str(value)) + ") Tj ET")
        y -= 20
    if footer:
        lines.append("BT /F1 8 Tf 56 60 Td (" + _esc(footer) + ") Tj ET")
    stream = "\n".join(lines).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 596 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)

"""Extraction / parsing interface. Parsers are chosen by the registry's Expected Output Type.
Exact document-processing technology (OCR, specific parsers) is deferred; these implementations
extract what the source response provides and retain the original file."""
import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ExtractedContent:
    payload_type: str                      # STRUCTURED | PDF | CSV | IMAGE
    records: list[dict[str, Any]]
    file_bytes: bytes | None = None
    file_ext: str | None = None
    pages: int | None = None
    size_kb: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)


class Extractor(Protocol):
    def extract(self, records: list[dict[str, Any]], documents: dict[str, bytes], ref_field: str | None) -> ExtractedContent: ...


def _pdf_pages(data: bytes) -> int:
    return max(1, len(re.findall(rb"/Type\s*/Page(?!s)", data)))


class StructuredExtractor:
    def extract(self, records, documents, ref_field):
        return ExtractedContent("STRUCTURED", records, fields=records[0] if records else {})


class PdfExtractor:
    def extract(self, records, documents, ref_field):
        first = records[0] if records else {}
        doc = documents.get(str(first.get(ref_field))) if ref_field else None
        pages = int(first.get("pages") or (_pdf_pages(doc) if doc else 1))
        size_kb = int(first.get("file_size_kb") or (len(doc) // 1024 if doc else 0))
        return ExtractedContent("PDF", records, file_bytes=doc, file_ext=".pdf", pages=pages, size_kb=size_kb, fields=first)


class CsvExtractor:
    def extract(self, records, documents, ref_field):
        buf = io.StringIO()
        clean = [{k: v for k, v in r.items() if k != "document_url"} for r in records]
        if clean:
            writer = csv.DictWriter(buf, fieldnames=list(clean[0].keys()))
            writer.writeheader()
            writer.writerows(clean)
        data = buf.getvalue().encode()
        return ExtractedContent("CSV", records, file_bytes=data, file_ext=".csv", size_kb=max(1, len(data) // 1024),
                                fields=clean[0] if clean else {})


class ImageExtractor(PdfExtractor):
    """JPG receipts: mock sources render them as PDF bundles; metadata extraction is the same."""
    def extract(self, records, documents, ref_field):
        out = super().extract(records, documents, ref_field)
        out.payload_type = "IMAGE"
        return out


def extractor_for(expected_output_type: str) -> Extractor:
    t = expected_output_type.upper()
    if "PDF" in t:
        return PdfExtractor()
    if "JPG" in t or "IMAGE" in t or "PNG" in t:
        return ImageExtractor()
    if "CSV" in t or "EXCEL" in t:
        return CsvExtractor()
    return StructuredExtractor()

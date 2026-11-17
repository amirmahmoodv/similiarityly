"""Turn uploaded files / pasted text into (text, meta) records."""

import csv
import io
import re
from pathlib import PurePath

TABULAR_EXT = {".xlsx", ".xlsm", ".csv", ".tsv"}
DOCUMENT_EXT = {".txt", ".md", ".docx", ".pdf"}

RecordInput = tuple[str, dict]


class ParseError(ValueError):
    """`args[0]` is a stable error code the frontend translates."""


def file_kind(filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext in TABULAR_EXT:
        return "tabular"
    if ext in DOCUMENT_EXT:
        return "document"
    raise ParseError("unsupported_file_type")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1256"):
        try:
            return data.decode(enc)
        except UnicodeError:
            continue
    raise ParseError("undecodable_text")


def _cell(value) -> str:
    return "" if value is None else str(value).strip()


def read_table(
    data: bytes, filename: str, sheet: str | None = None, has_header: bool = True
) -> tuple[list[str], list[list[str]], list[str]]:
    """Returns (columns, rows, sheet_names)."""
    ext = PurePath(filename).suffix.lower()
    sheets: list[str] = []
    if ext in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ParseError("invalid_excel_file") from exc
        sheets = wb.sheetnames
        ws = wb[sheet] if sheet and sheet in sheets else wb[sheets[0]]
        raw = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = _decode(data)
        delimiter = "\t" if ext == ".tsv" else ","
        if ext == ".csv":
            try:
                delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                pass
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        raw = [[_cell(c) for c in row] for row in reader]

    raw = [r for r in raw if any(r)]
    if not raw:
        return [], [], sheets
    width = max(len(r) for r in raw)
    raw = [r + [""] * (width - len(r)) for r in raw]
    if has_header:
        columns = [c or f"col_{i + 1}" for i, c in enumerate(raw[0])]
        rows = raw[1:]
    else:
        columns = [f"col_{i + 1}" for i in range(width)]
        rows = raw
    return columns, rows, sheets


def table_records(
    columns: list[str],
    rows: list[list[str]],
    text_columns: list[str] | None,
    label_column: str | None = None,
) -> list[RecordInput]:
    """One record per non-empty row. `label_column`, when given, names each
    record (meta["label"]) and is kept out of the compared text: a code such as
    "1.2-001" would otherwise make every record look a little alike."""
    label_idx = columns.index(label_column) if label_column in columns else None
    chosen = [c for c in (text_columns or []) if c in columns and c != label_column] or [
        c for c in columns if c != label_column
    ]
    idx = [columns.index(c) for c in chosen]
    records: list[RecordInput] = []
    for n, row in enumerate(rows, start=1):
        text = " | ".join(row[i] for i in idx if row[i])
        if text:
            meta = {"row": n, "fields": {c: v for c, v in zip(columns, row, strict=False) if v}}
            if label_idx is not None and row[label_idx].strip():
                meta["label"] = row[label_idx].strip()
            records.append((text, meta))
    return records


def read_document(data: bytes, filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext == ".docx":
        from docx import Document

        try:
            doc = Document(io.BytesIO(data))
        except Exception as exc:
            raise ParseError("invalid_docx_file") from exc
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            parts.extend(" | ".join(c.text for c in row.cells) for row in table.rows)
        return "\n\n".join(p for p in parts if p.strip())
    if ext == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception as exc:
            raise ParseError("invalid_pdf_file") from exc
    return _decode(data)


def split_text(text: str, split: str) -> list[RecordInput]:
    """`lines`: one record per line; `paragraphs`: per blank-line block; `whole`: one record."""
    if split == "lines":
        parts = text.splitlines()
    elif split == "paragraphs":
        parts = re.split(r"\n\s*\n", text)
    else:
        parts = [text]
    return [(p.strip(), {}) for p in parts if p.strip()]

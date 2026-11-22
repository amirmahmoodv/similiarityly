"""Excel export of a check: each record with its best match candidates.

Two layouts of the same data:

- "wide": one row per record, candidates pivoted into columns
  (candidate 1 label/score/text, candidate 2 ...). Reads like a report.
- "long": one row per record x candidate. The shape Excel's own PivotTable
  and filters want.

A candidate is a matched *record*: a record matched through several chunks
counts once, at its best score.
"""

import io
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from app.models import Match, Record

Layout = Literal["wide", "long"]
Lang = Literal["fa", "en"]

MAX_CANDIDATES = 100
_CELL_LIMIT = 32767  # Excel's hard limit for one cell
_PERCENT = "0.0%"

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_TEXT = {
    "en": {
        "results": "Results",
        "summary": "Summary",
        "ordinal": "Row",
        "label": "Label",
        "status": "Status",
        "score": "Top similarity",
        "count": "Candidates",
        "text": "Record text",
        "rank": "Candidate rank",
        "c_label": "Candidate label",
        "c_score": "Candidate similarity",
        "c_status": "Candidate status",
        "c_repo": "Candidate repository",
        "c_source": "Candidate source",
        "c_text": "Candidate text",
        "nth_label": "Candidate {n} label",
        "nth_score": "Candidate {n} similarity",
        "nth_text": "Candidate {n} text",
        "duplicate": "Duplicate",
        "similar": "Similar",
        "unique": "Unique",
        "repo": "Repository",
        "source": "Source",
        "similar_threshold": "Similar from",
        "duplicate_threshold": "Duplicate from",
        "total": "Records checked",
        "exported": "Records in this file",
        "per_record": "Candidates per record (up to)",
        "unreadable": "Damaged entries left out (repair the repository)",
    },
    "fa": {
        "results": "نتایج",
        "summary": "خلاصه",
        "ordinal": "ردیف",
        "label": "برچسب",
        "status": "وضعیت",
        "score": "بیشترین شباهت",
        "count": "تعداد نامزدها",
        "text": "متن رکورد",
        "rank": "رتبهٔ نامزد",
        "c_label": "برچسب نامزد",
        "c_score": "شباهت نامزد",
        "c_status": "وضعیت نامزد",
        "c_repo": "مخزن نامزد",
        "c_source": "منبع نامزد",
        "c_text": "متن نامزد",
        "nth_label": "برچسب نامزد {n}",
        "nth_score": "شباهت نامزد {n}",
        "nth_text": "متن نامزد {n}",
        "duplicate": "تکراری",
        "similar": "مشابه",
        "unique": "یکتا",
        "repo": "مخزن",
        "source": "منبع",
        "similar_threshold": "مشابه از",
        "duplicate_threshold": "تکراری از",
        "total": "رکوردهای بررسی‌شده",
        "exported": "رکوردهای این فایل",
        "per_record": "نامزد برای هر رکورد (حداکثر)",
        "unreadable": "ورودی‌های آسیب‌دیدهٔ کنارگذاشته (مخزن را تعمیر کنید)",
    },
}


@dataclass
class Candidate:
    label: str
    score: float
    text: str
    repo_id: str
    source_id: str


@dataclass
class ExportInfo:
    """What the Summary sheet states about the check."""

    repo_name: str
    source_name: str
    similar: float
    duplicate: float
    counts: dict[str, int]  # status -> records, over the whole check
    # Records and matches Qdrant could not decode; they are not in the file.
    unreadable: int = 0


def status_of(score: float, similar: float, duplicate: float) -> str:
    if score >= duplicate:
        return "duplicate"
    return "similar" if score >= similar else "unique"


def candidates_by_record(matches: list[Match]) -> dict[str, list[Candidate]]:
    """Every record's distinct matched records, best first."""
    best: dict[str, dict[str, Match]] = defaultdict(dict)
    for m in matches:
        seen = best[m.record_id].get(m.matched_record_id)
        if seen is None or m.score > seen.score:
            best[m.record_id][m.matched_record_id] = m
    return {
        record_id: [
            Candidate(
                m.matched_label, m.score, m.matched_text, m.matched_repo_id, m.matched_source_id
            )
            for m in sorted(found.values(), key=lambda m: m.score, reverse=True)
        ]
        for record_id, found in best.items()
    }


class _Sheet:
    """Appends rows cell by cell, keeping uploaded text inert."""

    def __init__(self, ws: Worksheet):
        self.ws = ws
        self.row = 0

    def append(self, values: list, percent: frozenset[int] = frozenset()) -> None:
        self.row += 1
        for col, value in enumerate(values, start=1):
            if value is None or value == "":
                continue
            if isinstance(value, str):
                cell = self.ws.cell(
                    self.row, col, ILLEGAL_CHARACTERS_RE.sub("", value)[:_CELL_LIMIT]
                )
                # openpyxl turns a leading "=" into a formula. Uploaded text
                # such as `=HYPERLINK(...)` must stay text.
                cell.data_type = "s"
            else:
                cell = self.ws.cell(self.row, col, value)
                if col in percent:
                    cell.number_format = _PERCENT


def _finish(sheet: _Sheet, widths: list[int], rtl: bool, table: str | None = None) -> None:
    ws = sheet.ws
    ws.sheet_view.rightToLeft = rtl
    ws.freeze_panes = "A2"
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    for cell in ws[1]:
        cell.font = Font(bold=True)
    # A named table: Excel offers it directly as a PivotTable source, with
    # filters on. A table needs at least one data row.
    if table and sheet.row > 1:
        ref = f"A1:{get_column_letter(len(widths))}{sheet.row}"
        tbl = Table(displayName=table, ref=ref)
        tbl.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(tbl)


def build_workbook(
    records: list[Record],
    matches: list[Match],
    info: ExportInfo,
    names: dict[str, str],
    *,
    layout: Layout,
    limit: int,
    lang: Lang,
) -> bytes:
    """`records` are the rows to write, in order. `names` maps repo and source
    ids to their names (missing = deleted since)."""
    t = _TEXT[lang]
    rtl = lang == "fa"
    found = candidates_by_record(matches)

    def nth(key: str, n: int) -> str:
        text = t[key].format(n=n)
        return text.translate(_FA_DIGITS) if rtl else text

    def status(score: float) -> str:
        return t[status_of(score, info.similar, info.duplicate)]

    def base(r: Record) -> list:
        return [
            r.ordinal,
            r.label,
            status(r.max_score),
            r.max_score,
            len(found.get(r.id, [])),
            r.text,
        ]

    head = [t["ordinal"], t["label"], t["status"], t["score"], t["count"], t["text"]]
    widths = [8, 18, 12, 16, 14, 60]

    wb = Workbook()
    sheet = _Sheet(wb.active)
    sheet.ws.title = t["results"]

    if layout == "wide":
        # No empty trailing columns when no record has that many candidates.
        shown = max(1, min(limit, max((len(found.get(r.id, [])) for r in records), default=0)))
        for n in range(1, shown + 1):
            head += [nth("nth_label", n), nth("nth_score", n), nth("nth_text", n)]
            widths += [18, 16, 60]
        sheet.append(head)
        percent = frozenset({4, *(6 + 3 * n - 1 for n in range(1, shown + 1))})
        for r in records:
            row = base(r)
            for c in found.get(r.id, [])[:shown]:
                row += [c.label, c.score, c.text]
            sheet.append(row, percent)
    else:
        head += [
            t["rank"],
            t["c_label"],
            t["c_score"],
            t["c_status"],
            t["c_repo"],
            t["c_source"],
            t["c_text"],
        ]
        widths += [14, 18, 16, 14, 22, 22, 60]
        sheet.append(head)
        percent = frozenset({4, 9})
        for r in records:
            top = found.get(r.id, [])[:limit]
            if not top:
                sheet.append(base(r), percent)  # the record still counts in a pivot
            for rank, c in enumerate(top, start=1):
                sheet.append(
                    [
                        *base(r),
                        rank,
                        c.label,
                        c.score,
                        status(c.score),
                        names.get(c.repo_id, ""),
                        names.get(c.source_id, ""),
                        c.text,
                    ],
                    percent,
                )
    _finish(sheet, widths, rtl, table="Results")

    summary = _Sheet(wb.create_sheet(t["summary"]))
    for key, value, pct in [
        ("repo", info.repo_name, False),
        ("source", info.source_name, False),
        ("similar_threshold", info.similar, True),
        ("duplicate_threshold", info.duplicate, True),
        ("total", sum(info.counts.values()), False),
        ("duplicate", info.counts.get("duplicate", 0), False),
        ("similar", info.counts.get("similar", 0), False),
        ("unique", info.counts.get("unique", 0), False),
        ("exported", len(records), False),
        ("per_record", limit, False),
        *([("unreadable", info.unreadable, False)] if info.unreadable else []),
    ]:
        summary.append([t[key], value], frozenset({2}) if pct else frozenset())
    summary.ws.sheet_view.rightToLeft = rtl
    summary.ws.column_dimensions["A"].width = 32
    summary.ws.column_dimensions["B"].width = 40
    for cell in summary.ws["A"]:
        cell.font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

import json
from pathlib import PurePath
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.repos import get_repo, job_out
from app.core.state import Services, get_services
from app.models import Job, Record, Source
from app.schemas import IngestMode, JobOut, PreviewOut
from app.services import parsers
from app.services.pipeline import run_ingest

router = APIRouter(tags=["ingest"])

PREVIEW_ROWS = 8


async def _read_upload(file: UploadFile, services: Services) -> bytes:
    """Read in chunks and stop at the limit, so an oversized upload is never
    loaded into memory whole."""
    limit = services.settings.max_upload_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, "file_too_large")
    data = bytes(buf)
    if not data:
        raise HTTPException(400, "empty_input")
    return data


@router.post("/sources/preview", response_model=PreviewOut)
async def preview(
    file: UploadFile = File(...),
    sheet: str | None = Form(None),
    has_header: bool = Form(True),
    services: Services = Depends(get_services),
):
    """Lets the UI show columns/sheets before the user picks what to embed."""
    data = await _read_upload(file, services)
    name = file.filename or ""
    try:
        if parsers.file_kind(name) == "tabular":
            columns, rows, sheets = parsers.read_table(data, name, sheet, has_header)
            return PreviewOut(
                kind="tabular",
                columns=columns,
                rows=rows[:PREVIEW_ROWS],
                total_rows=len(rows),
                sheets=sheets,
            )
        text = parsers.read_document(data, name)
        return PreviewOut(kind="document", excerpt=text[:600], char_count=len(text))
    except parsers.ParseError as exc:
        raise HTTPException(400, exc.args[0]) from exc


@router.post("/repos/{repo_id}/ingest", response_model=JobOut, status_code=202)
async def ingest(
    repo_id: str,
    input_kind: Literal["file", "text"] = Form(...),
    mode: IngestMode = Form("check_and_index"),
    name: str = Form("", max_length=300),
    # text input: "lines" (a list), "paragraphs", or "whole" (one document)
    split: Literal["whole", "lines", "paragraphs"] = Form("lines"),
    text: str | None = Form(None),
    # file input: {"sheet": str, "has_header": bool, "text_columns": [str]}
    options: str = Form("{}"),
    file: UploadFile | None = File(None),
    services: Services = Depends(get_services),
):
    repo = get_repo(repo_id, services)
    if repo.needs_reindex:
        raise HTTPException(409, "repo_needs_reindex")
    try:
        opts = json.loads(options or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid_options") from exc

    try:
        if input_kind == "file":
            if file is None:
                raise HTTPException(400, "empty_input")
            data = await _read_upload(file, services)
            filename = file.filename or "file"
            if parsers.file_kind(filename) == "tabular":
                columns, rows, _ = parsers.read_table(
                    data, filename, opts.get("sheet"), bool(opts.get("has_header", True))
                )
                records = parsers.table_records(columns, rows, opts.get("text_columns"))
                kind = "csv" if PurePath(filename).suffix.lower() in {".csv", ".tsv"} else "excel"
            else:
                records = parsers.split_text(parsers.read_document(data, filename), "whole")
                kind = "document"
            default_name = filename
        else:
            records = parsers.split_text(text or "", split)
            kind = "list" if split == "lines" else "paste"
            default_name = (records[0][0][:40] if records else "").strip()
    except parsers.ParseError as exc:
        raise HTTPException(400, exc.args[0]) from exc

    if not records:
        raise HTTPException(400, "empty_input")

    indexed = mode != "check_only"
    source = Source(
        repo_id=repo.id,
        name=name.strip() or default_name,
        kind=kind,
        record_count=len(records),
        indexed=indexed,
    )
    job = Job(repo_id=repo.id, source_id=source.id, kind="ingest", mode=mode, total=len(records))
    services.meta.put(source)
    services.meta.put_many(
        Record(repo_id=repo.id, source_id=source.id, ordinal=i, text=t, meta=m, indexed=indexed)
        for i, (t, m) in enumerate(records, start=1)
    )
    services.meta.put(job)
    services.submit(run_ingest, job.id)
    return job_out(services.meta.get(Job, job.id), services)

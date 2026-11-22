import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.repos import job_out
from app.core.state import Services, get_services
from app.models import Job, Match, Record, Repo, Source
from app.schemas import JobOut, JobSummary, MatchOut, RecordOut, RecordPage, RepoConfig
from app.services.export_xlsx import MAX_CANDIDATES, ExportInfo, Lang, Layout, build_workbook
from app.services.meta_store import Ranges

router = APIRouter(tags=["jobs"])

StatusFilter = Literal["all", "duplicate", "similar", "unique"]


def _job(job_id: str, services: Services) -> Job:
    job = services.meta.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job_not_found")
    return job


def _thresholds(job: Job, services: Services) -> tuple[float, float]:
    """Statuses are derived at read time, so retuning thresholds is retroactive."""
    repo = services.meta.get(Repo, job.repo_id)
    sim = RepoConfig.model_validate(repo.config).similarity
    return sim.similar_threshold, sim.duplicate_threshold


def _status(score: float, similar: float, duplicate: float) -> str:
    if score >= duplicate:
        return "duplicate"
    return "similar" if score >= similar else "unique"


def _score_range(status: StatusFilter, similar: float, duplicate: float) -> Ranges | None:
    if status == "duplicate":
        return {"max_score": {"gte": duplicate}}
    if status == "similar":
        return {"max_score": {"gte": similar, "lt": duplicate}}
    if status == "unique":
        return {"max_score": {"lt": similar}}
    return None


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    repo_id: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    services: Services = Depends(get_services),
):
    where = {"repo_id": repo_id} if repo_id else None
    jobs = services.meta.find(Job, where, order_by="created_ts", desc=True, limit=limit)
    return [job_out(j, services) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def read_job(job_id: str, services: Services = Depends(get_services)):
    return job_out(_job(job_id, services), services)


@router.get("/jobs/{job_id}/summary", response_model=JobSummary)
def job_summary(job_id: str, services: Services = Depends(get_services)):
    job = _job(job_id, services)
    similar, duplicate = _thresholds(job, services)

    def count(status: StatusFilter) -> int:
        if not job.source_id:
            return 0
        return services.meta.count(
            Record, {"source_id": job.source_id}, _score_range(status, similar, duplicate)
        )

    return JobSummary(
        total=count("all"),
        duplicate=count("duplicate"),
        similar=count("similar"),
        unique=count("unique"),
        similar_threshold=similar,
        duplicate_threshold=duplicate,
    )


@router.get("/jobs/{job_id}/records", response_model=RecordPage)
def job_records(
    job_id: str,
    status: StatusFilter = "all",
    sort: Literal["score", "ordinal"] = "score",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    services: Services = Depends(get_services),
):
    job = _job(job_id, services)
    similar, duplicate = _thresholds(job, services)
    if not job.source_id:
        return RecordPage(items=[], total=0, page=page, page_size=page_size)
    where = {"source_id": job.source_id}
    ranges = _score_range(status, similar, duplicate)
    rows = services.meta.find(
        Record,
        where,
        ranges,
        order_by="max_score" if sort == "score" else "ordinal",
        desc=sort == "score",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [
        RecordOut(
            id=r.id,
            ordinal=r.ordinal,
            text=r.text,
            label=r.label,
            meta=r.meta,
            chunk_count=r.chunk_count,
            max_score=r.max_score,
            match_count=r.match_count,
            status=_status(r.max_score, similar, duplicate),
        )
        for r in rows
    ]
    total = services.meta.count(Record, where, ranges)
    return RecordPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/records/{record_id}/matches", response_model=list[MatchOut])
def record_matches(record_id: str, services: Services = Depends(get_services)):
    matches = services.meta.find(
        Match, {"record_id": record_id}, order_by="score", desc=True, limit=100
    )
    repos: dict[str, str] = {}
    sources: dict[str, str] = {}
    out = []
    for m in matches:
        if m.matched_repo_id not in repos:
            repo = services.meta.get(Repo, m.matched_repo_id)
            repos[m.matched_repo_id] = repo.name if repo else ""
        if m.matched_source_id not in sources:
            source = services.meta.get(Source, m.matched_source_id)
            sources[m.matched_source_id] = source.name if source else ""
        item = MatchOut.model_validate(m)
        item.matched_repo_name = repos[m.matched_repo_id]
        item.matched_source_name = sources[m.matched_source_id]
        out.append(item)
    return out


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralize spreadsheet formulas (CSV injection): uploaded text such as
    `=HYPERLINK(...)` would otherwise run when the export is opened in Excel."""
    return "'" + value if value.startswith(_FORMULA_START) else value


@router.get("/jobs/{job_id}/export.csv")
def export_job(job_id: str, services: Services = Depends(get_services)):
    """One row per record with its best match. UTF-8 BOM so Excel reads Persian."""
    job = _job(job_id, services)
    similar, duplicate = _thresholds(job, services)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ordinal",
            "label",
            "status",
            "score",
            "match_count",
            "text",
            "best_match_label",
            "best_match_text",
        ]
    )
    records = services.meta.all(Record, {"source_id": job.source_id}) if job.source_id else []
    for r in sorted(records, key=lambda r: r.ordinal):
        writer.writerow(
            [
                r.ordinal,
                _csv_safe(r.label),
                _status(r.max_score, similar, duplicate),
                f"{r.max_score:.4f}",
                r.match_count,
                _csv_safe(r.text),
                _csv_safe(r.best_match_label),
                _csv_safe(r.best_match_text),
            ]
        )
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="similarity-{job.id}.csv"'},
    )


@router.get("/jobs/{job_id}/export.xlsx")
def export_job_xlsx(
    job_id: str,
    layout: Layout = "wide",
    candidates: int = Query(3, ge=1, le=MAX_CANDIDATES),
    status: StatusFilter = "all",
    lang: Lang = "en",
    services: Services = Depends(get_services),
):
    """Records with their top `candidates` matched records and labels.
    `layout` pivots the candidates into columns ("wide") or gives each its own
    row ("long"); see services/export_xlsx.py."""
    job = _job(job_id, services)
    similar, duplicate = _thresholds(job, services)
    where = {"source_id": job.source_id}
    # A report of what can be read beats no report: entries Qdrant cannot
    # decode are left out and counted on the Summary sheet (a repair removes them).
    unreadable: list[str] = []
    records = services.meta.all(Record, where, unreadable) if job.source_id else []
    matches = services.meta.all(Match, where, unreadable) if job.source_id else []

    counts = {"duplicate": 0, "similar": 0, "unique": 0}
    for r in records:
        counts[_status(r.max_score, similar, duplicate)] += 1
    if status != "all":
        records = [r for r in records if _status(r.max_score, similar, duplicate) == status]
    records.sort(key=lambda r: r.ordinal)

    meta = services.meta
    repos = meta.get_many(Repo, [job.repo_id, *(m.matched_repo_id for m in matches)])
    sources = meta.get_many(Source, [job.source_id or "", *(m.matched_source_id for m in matches)])
    names = {e.id: e.name for e in (*repos.values(), *sources.values())}
    content = build_workbook(
        records,
        matches,
        ExportInfo(
            repo_name=names.get(job.repo_id, ""),
            source_name=names.get(job.source_id or "", ""),
            similar=similar,
            duplicate=duplicate,
            counts=counts,
            unreadable=len(unreadable),
        ),
        names,
        layout=layout,
        limit=candidates,
        lang=lang,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="similarity-{job.id}.xlsx"'},
    )

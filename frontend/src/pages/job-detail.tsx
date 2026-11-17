import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, Download, SearchX } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { AnimatedTabs } from "@/components/motion";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  LoadingPanel,
  PageHeader,
  ScoreMeter,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { Stat } from "@/components/ui/stat";
import { JobProgress, JobStatusLabel } from "@/features/jobs/job-row";
import { useI18n } from "@/i18n";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { transitions } from "@/lib/motion";
import type { JobSummary, RecordItem, RecordStatus } from "@/lib/types";

const PAGE_SIZE = 25;
type Filter = RecordStatus | "all";
const FILTERS: Filter[] = ["all", "duplicate", "similar", "unique"];

function statusOf(score: number, summary: JobSummary): RecordStatus {
  if (score >= summary.duplicate_threshold) return "duplicate";
  return score >= summary.similar_threshold ? "similar" : "unique";
}

function ExportButton({ jobId }: { jobId: string }) {
  const { t, err } = useI18n();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.exportCsv(jobId);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="secondary" loading={busy} onClick={run}>
        {!busy && <Download className="size-4" aria-hidden="true" />}
        {t.results.export}
      </Button>
      {error != null && (
        <p role="alert" className="text-xs text-destructive">
          {err(error)}
        </p>
      )}
    </div>
  );
}

function Matches({ record, summary }: { record: RecordItem; summary: JobSummary }) {
  const { t, pct } = useI18n();
  const matches = useQuery({
    queryKey: ["matches", record.id],
    queryFn: () => api.matches(record.id),
  });

  if (matches.isError) return <ErrorNote error={matches.error} onRetry={() => matches.refetch()} />;
  if (!matches.data) return <Skeleton className="h-20" />;
  if (matches.data.length === 0) {
    return <p className="text-sm text-muted-foreground">{t.results.noMatches}</p>;
  }
  return (
    <ul className="space-y-3">
      {matches.data.map((m) => (
        <li key={m.id} className="rounded-xl border bg-card p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="text-muted-foreground">
              {t.results.foundIn(
                m.matched_repo_name || t.common.none,
                m.matched_source_name || t.results.deletedSource,
              )}
            </span>
            <span className="flex items-center gap-2">
              {m.vector_score !== null && (
                <span className="nums text-muted-foreground">
                  {t.results.firstStage(pct(m.vector_score))}
                </span>
              )}
              <StatusBadge status={statusOf(m.score, summary)} />
              <span className="nums text-sm font-semibold">{pct(m.score)}</span>
            </span>
          </div>
          <div className="grid gap-3 text-sm md:grid-cols-2">
            {(
              [
                [t.results.thisChunk, m.chunk_text],
                [t.results.matchedChunk, m.matched_text],
              ] as const
            ).map(([label, text]) => (
              <div key={label} className="min-w-0">
                <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
                <p dir="auto" className="whitespace-pre-wrap break-words rounded-lg bg-muted/60 p-2.5">
                  {text}
                </p>
              </div>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

function RecordRow({ record, summary }: { record: RecordItem; summary: JobSummary }) {
  const { t, n } = useI18n();
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = React.useState(false);
  const panelId = React.useId();
  const expandable = record.match_count > 0;

  return (
    <li className="border-t first:border-t-0">
      <div className="grid grid-cols-[2.5rem_1fr] items-center gap-x-3 gap-y-2 px-4 py-3 md:grid-cols-[3rem_1fr_11rem_5.5rem_3.5rem]">
        <span className="nums text-sm text-muted-foreground">{n(record.ordinal)}</span>
        <p dir="auto" className={cn("min-w-0 break-words text-sm", !open && "line-clamp-2")}>
          {record.text}
        </p>
        <div className="col-start-2 flex items-center gap-3 md:col-start-auto">
          <ScoreMeter score={record.max_score} status={record.status} />
        </div>
        <div className="col-start-2 flex items-center justify-between gap-2 md:col-start-auto">
          <StatusBadge status={record.status} />
          <span className="text-xs text-muted-foreground md:hidden">
            <span className="nums">{n(record.match_count)}</span> {t.units.matches}
          </span>
        </div>
        <button
          type="button"
          disabled={!expandable}
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={t.results.showMatches(n(record.ordinal))}
          onClick={() => setOpen(!open)}
          className="col-start-2 flex items-center gap-1 justify-self-start rounded-md p-1 text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:invisible md:col-start-auto md:justify-self-end"
        >
          <span className="nums hidden text-xs md:inline">{n(record.match_count)}</span>
          <motion.span
            animate={{ rotate: open ? 180 : 0 }}
            transition={reduceMotion ? { duration: 0.01 } : transitions.fast}
            className="inline-flex"
          >
            <ChevronDown className="size-4" aria-hidden="true" />
          </motion.span>
        </button>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={panelId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={reduceMotion ? { duration: 0.01 } : transitions.standard}
            className="overflow-hidden"
          >
            <div className="bg-muted/40 px-4 py-3">
              <Matches record={record} summary={summary} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const { t, n, pct, dir } = useI18n();
  const queryClient = useQueryClient();
  const [filter, setFilter] = React.useState<Filter>("all");
  const [page, setPage] = React.useState(1);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "queued" || status === "running" ? 1000 : false;
    },
  });
  const status = job.data?.status;
  const finished = status === "done" || status === "failed";
  const isIngest = job.data?.kind === "ingest";

  // Results fill in as the job advances; refresh them with each progress tick.
  const tick = finished ? "final" : (job.data?.processed ?? 0);
  const summary = useQuery({
    queryKey: ["job-summary", jobId, tick],
    queryFn: () => api.jobSummary(jobId),
    enabled: isIngest,
    placeholderData: keepPreviousData,
  });
  const records = useQuery({
    queryKey: ["job-records", jobId, filter, page, tick],
    queryFn: () => api.jobRecords(jobId, filter, page, PAGE_SIZE),
    enabled: isIngest,
    placeholderData: keepPreviousData,
  });

  React.useEffect(() => {
    if (finished) {
      for (const key of ["repo", "repos", "stats", "sources", "jobs"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    }
  }, [finished, queryClient]);

  if (job.isError) {
    const missing = job.error instanceof ApiError && job.error.status === 404;
    return missing ? (
      <EmptyState icon={<SearchX className="size-6" aria-hidden="true" />} title={t.results.notFound} />
    ) : (
      <ErrorNote error={job.error} onRetry={() => job.refetch()} />
    );
  }
  if (!job.data) {
    return (
      <div className="space-y-4" role="status" aria-label={t.common.loading}>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-24" />
        <LoadingPanel className="h-64" />
      </div>
    );
  }

  const data = job.data;
  const pages = records.data ? Math.max(1, Math.ceil(records.data.total / PAGE_SIZE)) : 1;
  const s = summary.data;

  return (
    <>
      <Link
        to={`/repos/${data.repo_id}`}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowRight className={cn("size-4", dir === "ltr" && "rotate-180")} aria-hidden="true" />
        {t.results.backToRepo}
        {data.repo_name && <span className="font-medium text-foreground">{data.repo_name}</span>}
      </Link>

      <PageHeader
        title={isIngest ? t.results.title : t.results.reindexTitle}
        subtitle={isIngest ? `${data.source_name} · ${t.mode[data.mode].title}` : undefined}
        actions={
          isIngest && status === "done" ? (
            <ExportButton jobId={data.id} />
          ) : undefined
        }
      />

      <Card className="mb-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <JobStatusLabel job={data} />
          {s && isIngest && (
            <span className="text-xs text-muted-foreground">
              {t.results.thresholds(pct(s.similar_threshold), pct(s.duplicate_threshold))}
            </span>
          )}
        </div>
        <JobProgress job={data} />
        {status === "failed" && (
          <div role="alert" className="space-y-1.5 text-sm">
            <p dir="auto" className="break-words text-destructive">
              {data.error === "interrupted"
                ? t.job.interrupted
                : // A stable code; jobs from older versions stored raw text, shown as is.
                  ((t.errors as Record<string, string>)[data.error ?? ""] ??
                  data.error ??
                  t.errors.unknown_error)}
            </p>
            {data.error_detail && (
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer select-none rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {t.settings.details}
                </summary>
                <pre dir="ltr" className="mt-1 whitespace-pre-wrap break-all text-start font-mono">
                  {data.error_detail}
                </pre>
              </details>
            )}
          </div>
        )}
        {!isIngest && status === "done" && <p className="text-sm text-uniq">{t.results.reindexDone}</p>}
      </Card>

      {isIngest && data.mode !== "index_only" && (
        <>
          <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {s ? (
              <>
                <Stat label={t.status.all} value={s.total} unit={t.units.records} />
                <Stat label={t.status.duplicate} value={s.duplicate} unit={t.units.records} tone="dup" />
                <Stat label={t.status.similar} value={s.similar} unit={t.units.records} tone="sim" />
                <Stat label={t.status.unique} value={s.unique} unit={t.units.records} tone="uniq" />
              </>
            ) : (
              Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)
            )}
          </div>

          <AnimatedTabs
            className="mb-3"
            label={t.results.filter}
            value={filter}
            onValueChange={(value) => {
              setFilter(value as Filter);
              setPage(1);
            }}
            items={FILTERS.map((id) => ({
              id,
              label: (
                <>
                  {t.status[id]}
                  {s && (
                    <span className="nums ms-1.5 text-xs text-muted-foreground">
                      {n(id === "all" ? s.total : s[id])}
                    </span>
                  )}
                </>
              ),
            }))}
          />

          {records.isError ? (
            <ErrorNote error={records.error} onRetry={() => records.refetch()} />
          ) : !records.data || !s ? (
            <Skeleton className="h-64" />
          ) : records.data.items.length === 0 ? (
            <EmptyState icon={<SearchX className="size-6" aria-hidden="true" />} title={t.results.noRecords} />
          ) : (
            <Card className={cn("p-0 transition-opacity", records.isPlaceholderData && "opacity-60")}>
              <div
                aria-hidden="true"
                className="hidden grid-cols-[3rem_1fr_11rem_5.5rem_3.5rem] gap-x-3 border-b bg-muted/60 px-4 py-2 text-xs font-medium text-muted-foreground md:grid"
              >
                <span>{t.results.ordinal}</span>
                <span>{t.results.text}</span>
                <span>{t.results.score}</span>
                <span>{t.results.status}</span>
                <span className="text-end">{t.results.matchCount}</span>
              </div>
              <ul>
                {records.data.items.map((record) => (
                  <RecordRow key={record.id} record={record} summary={s} />
                ))}
              </ul>
            </Card>
          )}

          {pages > 1 && (
            <nav className="mt-4 flex items-center justify-center gap-3" aria-label={t.results.title}>
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                {t.common.previous}
              </Button>
              <span className="nums text-sm text-muted-foreground">
                {t.common.page(n(page), n(pages))}
              </span>
              <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                {t.common.next}
              </Button>
            </nav>
          )}
        </>
      )}
    </>
  );
}

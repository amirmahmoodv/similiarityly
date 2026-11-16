import { ChevronLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { BotStatus, type BotState } from "@/components/motion";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import type { Job, JobStatus } from "@/lib/types";

const botState: Record<JobStatus, BotState> = {
  queued: "idle",
  running: "tool",
  done: "success",
  failed: "error",
};

const statusTone: Record<JobStatus, string> = {
  queued: "text-muted-foreground",
  running: "text-primary",
  done: "text-uniq",
  failed: "text-dup",
};

/** Truthful job state: the indicator only animates while the job is actually running. */
export function JobStatusLabel({ job }: { job: Job }) {
  const { t } = useI18n();
  return (
    <BotStatus state={botState[job.status]} label={t.job[job.status]} className={statusTone[job.status]} />
  );
}

export function JobProgress({ job }: { job: Job }) {
  const { t, n } = useI18n();
  const ratio = job.total ? Math.min(1, job.processed / job.total) : job.status === "done" ? 1 : 0;
  return (
    <div className="flex items-center gap-3">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={job.total}
        aria-valuenow={job.processed}
        aria-label={t.job[job.status]}
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full origin-[inline-start] rounded-full transition-[width] duration-300",
            job.status === "failed"
              ? "bg-dup"
              : "bg-primary shadow-[0_0_10px_-1px_var(--primary)]",
          )}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <span className="nums shrink-0 text-xs text-muted-foreground">
        {t.job.processed(n(job.processed), n(job.total))} {t.units.records}
      </span>
    </div>
  );
}

export function JobRow({ job, showRepo = true }: { job: Job; showRepo?: boolean }) {
  const { t, date, dir } = useI18n();
  const title = job.kind === "reindex" ? t.job.reindex : job.source_name || t.job.ingest;
  return (
    <Link
      to={`/jobs/${job.id}`}
      className="hud-panel group mb-2 block rounded-xl border px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <div className="truncate font-medium">{title}</div>
          <div className="text-xs text-muted-foreground">
            {showRepo && job.repo_name ? `${job.repo_name} · ` : ""}
            {date(job.created_at)}
          </div>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <JobStatusLabel job={job} />
          <ChevronLeft
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-200 group-hover:text-primary",
              dir === "ltr" ? "rotate-180 group-hover:translate-x-1" : "group-hover:-translate-x-1",
            )}
            aria-hidden="true"
          />
        </div>
      </div>
      {(job.status === "running" || job.status === "queued") && (
        <div className="mt-2">
          <JobProgress job={job} />
        </div>
      )}
    </Link>
  );
}

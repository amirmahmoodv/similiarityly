import { useQuery } from "@tanstack/react-query";
import { Boxes, Database, FileText, GitCompareArrows, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { AnimatedList } from "@/components/motion";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/primitives";
import { Stat } from "@/components/ui/stat";
import { JobRow } from "@/features/jobs/job-row";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";

const ACTIVE = new Set(["queued", "running"]);

export function DashboardPage() {
  const { t } = useI18n();
  const jobs = useQuery({
    queryKey: ["jobs", "recent"],
    queryFn: () => api.jobs(undefined, 8),
    refetchInterval: (q) => (q.state.data?.some((j) => ACTIVE.has(j.status)) ? 1500 : false),
  });
  const busy = jobs.data?.some((j) => ACTIVE.has(j.status)) ?? false;
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    refetchInterval: busy ? 2000 : false,
  });

  const icon = "size-4";
  return (
    <>
      <PageHeader title={t.dashboard.title} subtitle={t.dashboard.subtitle} />

      {stats.isError ? (
        <ErrorNote error={stats.error} onRetry={() => stats.refetch()} />
      ) : (
        <div className="hud-stagger grid grid-cols-2 gap-4 lg:grid-cols-4">
          {stats.data ? (
            <>
              <Stat
                label={t.dashboard.repos}
                value={stats.data.repos}
                unit={t.units.repos}
                icon={<Database className={icon} aria-hidden="true" />}
              />
              <Stat
                label={t.dashboard.records}
                value={stats.data.records}
                unit={t.units.records}
                icon={<FileText className={icon} aria-hidden="true" />}
              />
              <Stat
                label={t.dashboard.chunks}
                value={stats.data.chunks}
                unit={t.units.chunks}
                icon={<Boxes className={icon} aria-hidden="true" />}
              />
              <Stat
                label={t.dashboard.matches}
                value={stats.data.matches}
                unit={t.units.matches}
                icon={<GitCompareArrows className={icon} aria-hidden="true" />}
              />
            </>
          ) : (
            Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)
          )}
        </div>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">{t.dashboard.recentJobs}</h2>
        {jobs.isError ? (
          <ErrorNote error={jobs.error} onRetry={() => jobs.refetch()} />
        ) : !jobs.data ? (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : jobs.data.length === 0 ? (
          <EmptyState
            icon={<GitCompareArrows className="size-6" aria-hidden="true" />}
            title={t.dashboard.noJobs}
            action={
              <Link
                to="/repos"
                className="hud-sheen inline-flex shadow-[0_0_20px_-6px_var(--primary)] items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground outline-none transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <Plus className="size-4" aria-hidden="true" />
                {t.dashboard.start}
              </Link>
            }
          />
        ) : (
          <AnimatedList>
            {jobs.data.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </AnimatedList>
        )}
      </section>
    </>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FolderOpen, RefreshCw, Trash2, TriangleAlert } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AnimatedList, AnimatedTabs } from "@/components/motion";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button, EmptyState, ErrorNote, LoadingPanel, PageHeader, Skeleton } from "@/components/ui/primitives";
import { ChunksPanel } from "@/features/chunks/chunks-panel";
import { IngestPanel } from "@/features/ingest/ingest-panel";
import { SearchPanel } from "@/features/search/search-panel";
import { RepoConfigForm } from "@/features/repos/repo-config-form";
import { useI18n } from "@/i18n";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Repo, Source } from "@/lib/types";

type Tab = "load" | "search" | "chunks" | "sources" | "settings";
const TABS: Tab[] = ["load", "search", "chunks", "sources", "settings"];

function SourcesList({ repo }: { repo: Repo }) {
  const { t, n, date } = useI18n();
  const queryClient = useQueryClient();
  const sources = useQuery({ queryKey: ["sources", repo.id], queryFn: () => api.sources(repo.id) });
  const [target, setTarget] = React.useState<Source | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSource(id),
    onSuccess: () => {
      for (const key of ["sources", "repo", "repos", "stats", "jobs"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      setTarget(null);
    },
  });

  if (sources.isError) return <ErrorNote error={sources.error} onRetry={() => sources.refetch()} />;
  if (!sources.data) return <Skeleton className="h-32" />;
  if (sources.data.length === 0) {
    return <EmptyState icon={<FolderOpen className="size-6" aria-hidden="true" />} title={t.sources.empty} />;
  }

  return (
    <>
      <AnimatedList>
        {sources.data.map((source) => (
          <div
            key={source.id}
            className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border bg-card px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <div className="break-words font-medium">{source.name}</div>
              <div className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                <span>{t.sources.kind[source.kind]}</span>
                <span aria-hidden="true">·</span>
                <span>
                  <span className="nums">{n(source.record_count)}</span> {t.units.records}
                </span>
                <span aria-hidden="true">·</span>
                <span>{date(source.created_at)}</span>
              </div>
            </div>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                source.indexed ? "bg-uniq-soft text-uniq" : "bg-muted text-muted-foreground",
              )}
            >
              {source.indexed ? t.sources.indexed : t.sources.checkOnly}
            </span>
            {source.last_job_id && (
              <Link
                to={`/jobs/${source.last_job_id}`}
                className="rounded-lg border px-3 py-1.5 text-sm font-medium outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t.sources.results}
              </Link>
            )}
            <Button
              variant="ghost"
              size="sm"
              aria-label={t.sources.deleteLabel(source.name)}
              className="text-destructive"
              onClick={() => {
                remove.reset();
                setTarget(source);
              }}
            >
              <Trash2 className="size-4" aria-hidden="true" />
            </Button>
          </div>
        ))}
      </AnimatedList>
      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => !open && setTarget(null)}
        title={t.sources.deleteTitle}
        body={target ? t.sources.deleteBody(target.name) : ""}
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() => target && remove.mutate(target.id)}
      />
    </>
  );
}

export function RepoDetailPage() {
  const { repoId = "" } = useParams();
  const { t, n, dir } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : "load";
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  const repo = useQuery({ queryKey: ["repo", repoId], queryFn: () => api.repo(repoId) });

  const reindex = useMutation({
    mutationFn: () => api.reindex(repoId),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/jobs/${job.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteRepo(repoId),
    onSuccess: () => {
      for (const key of ["repos", "stats", "jobs"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      navigate("/repos");
    },
  });

  const back = (
    <Link
      to="/repos"
      className="mb-4 inline-flex items-center gap-1.5 rounded-md text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ArrowRight className={cn("size-4", dir === "ltr" && "rotate-180")} aria-hidden="true" />
      {t.repo.backToRepos}
    </Link>
  );

  if (repo.isError) {
    const missing = repo.error instanceof ApiError && repo.error.status === 404;
    return (
      <>
        {back}
        {missing ? (
          <EmptyState icon={<FolderOpen className="size-6" aria-hidden="true" />} title={t.repo.notFound} />
        ) : (
          <ErrorNote error={repo.error} onRetry={() => repo.refetch()} />
        )}
      </>
    );
  }
  if (!repo.data) {
    return (
      <div className="space-y-4" role="status" aria-label={t.common.loading}>
        <Skeleton className="h-10 w-64" />
        <LoadingPanel className="h-64" />
      </div>
    );
  }

  const data = repo.data;
  const facts = [
    [data.source_count, t.units.sources],
    [data.record_count, t.units.records],
    [data.chunk_count, t.units.chunks],
    ...(data.vector_size ? ([[data.vector_size, t.units.dimensions]] as const) : []),
  ] as const;

  return (
    <>
      {back}
      <PageHeader
        title={data.name}
        subtitle={
          <>
            {data.description && <span className="block">{data.description}</span>}
            <span className="mt-1 flex flex-wrap gap-x-3">
              {facts.map(([value, unit]) => (
                <span key={unit}>
                  <span className="nums font-semibold text-foreground">{n(value)}</span> {unit}
                </span>
              ))}
            </span>
          </>
        }
        actions={
          <Button
            variant="ghost"
            className="text-destructive"
            onClick={() => {
              remove.reset();
              setConfirmDelete(true);
            }}
          >
            <Trash2 className="size-4" aria-hidden="true" />
            {t.repo.deleteRepo}
          </Button>
        }
      />

      {data.needs_reindex && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-sim/50 bg-sim-soft px-4 py-3 text-sm"
        >
          <TriangleAlert className="size-4 shrink-0 text-sim" aria-hidden="true" />
          <span className="min-w-48 flex-1">{t.repo.reindexBanner}</span>
          <Button size="sm" loading={reindex.isPending} onClick={() => reindex.mutate()}>
            {!reindex.isPending && <RefreshCw className="size-4" aria-hidden="true" />}
            {t.repo.reindexAction}
          </Button>
          {reindex.isError && (
            <div className="w-full">
              <ErrorNote error={reindex.error} />
            </div>
          )}
        </div>
      )}

      <AnimatedTabs
        className="mb-5"
        label={t.repo.tabs.label}
        value={tab}
        onValueChange={(value) => setParams({ tab: value }, { replace: true })}
        items={TABS.map((id) => ({ id, label: t.repo.tabs[id] }))}
      />

      <div role="tabpanel" aria-label={t.repo.tabs[tab]}>
        {tab === "load" && <IngestPanel repo={data} />}
        {tab === "search" && <SearchPanel repo={data} />}
        {tab === "chunks" && <ChunksPanel repo={data} />}
        {tab === "sources" && <SourcesList repo={data} />}
        {tab === "settings" && <RepoConfigForm key={data.id} repo={data} />}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t.repo.deleteTitle}
        body={t.repo.deleteBody(data.name)}
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

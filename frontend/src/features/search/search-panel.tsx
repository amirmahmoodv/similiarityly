import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleCheck, Search, SearchX, TriangleAlert } from "lucide-react";
import * as React from "react";
import { AnimatedList } from "@/components/motion";
import { NumericInput } from "@/components/ui/numeric-input";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  RecordLabel,
  ScoreMeter,
  Skeleton,
  StatusBadge,
  TextArea,
} from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { rawToNumber } from "@/lib/format";
import type { RecordStatus, Repo } from "@/lib/types";

function IndexStatusCard({ repo }: { repo: Repo }) {
  const { t, n } = useI18n();
  const status = useQuery({
    queryKey: ["repo-index", repo.id, repo.chunk_count, repo.needs_reindex],
    queryFn: () => api.indexStatus(repo.id),
  });

  if (status.isError) return <ErrorNote error={status.error} onRetry={() => status.refetch()} />;
  if (!status.data) return <Skeleton className="h-40" />;
  const s = status.data;
  const problems = t.search.problems as Record<string, string>;
  const distances = t.config.distances as Record<string, string>;

  const facts: [string, React.ReactNode][] = [
    [t.search.points, <><span className="nums">{n(s.points)}</span> {t.units.chunks}</>],
    [
      t.search.dimensions,
      s.vector_size === null ? (
        t.common.none
      ) : (
        <><span className="nums">{n(s.vector_size)}</span> {t.units.dimensions}</>
      ),
    ],
    [t.config.distance, s.distance ? (distances[s.distance] ?? s.distance) : t.common.none],
    [t.search.backend, t.app.qdrant[s.mode]],
  ];

  return (
    <Card className="space-y-3">
      <h2 className="font-semibold">{t.search.indexTitle}</h2>
      <div
        role="status"
        className={
          s.searchable
            ? "flex items-start gap-2 rounded-lg bg-uniq-soft px-3 py-2 text-sm text-uniq"
            : "flex items-start gap-2 rounded-lg bg-sim-soft px-3 py-2 text-sm text-sim"
        }
      >
        {s.searchable ? (
          <CircleCheck className="mt-1 size-4 shrink-0" aria-hidden="true" />
        ) : (
          <TriangleAlert className="mt-1 size-4 shrink-0" aria-hidden="true" />
        )}
        <span>
          {s.searchable ? t.search.ready : (problems[s.problem ?? ""] ?? t.errors.unknown_error)}
        </span>
      </div>
      <dl className="space-y-1.5 text-sm">
        {facts.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="text-end font-medium">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export function SearchPanel({ repo }: { repo: Repo }) {
  const { t, n, pct } = useI18n();
  const [query, setQuery] = React.useState("");
  const [topK, setTopK] = React.useState("10");
  const sim = repo.config.similarity;

  const search = useMutation({
    mutationFn: () => api.search(repo.id, query.trim(), rawToNumber(topK)),
  });

  const k = rawToNumber(topK);
  const topKValid = Number.isInteger(k) && k >= 1 && k <= 100;
  const canSearch = query.trim().length > 0 && topKValid && !repo.needs_reindex;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (canSearch && !search.isPending) search.mutate();
  };

  const statusOf = (score: number): RecordStatus =>
    score >= sim.duplicate_threshold
      ? "duplicate"
      : score >= sim.similar_threshold
        ? "similar"
        : "unique";

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[1fr_20rem]">
      <div className="min-w-0 space-y-4">
        <Card>
          <form onSubmit={submit} className="space-y-4">
            <Field label={t.search.query} hint={t.search.queryHint}>
              {(ids) => (
                <TextArea
                  {...ids}
                  rows={3}
                  dir="auto"
                  value={query}
                  placeholder={t.search.placeholder}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(e);
                  }}
                />
              )}
            </Field>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <Field
                label={t.search.topK}
                error={topKValid ? undefined : t.config.errors.top_k}
                className="w-44"
              >
                {(ids) => (
                  <NumericInput
                    {...ids}
                    value={topK}
                    unit={t.units.results}
                    invalid={!topKValid}
                    onValueChange={setTopK}
                  />
                )}
              </Field>
              <Button type="submit" loading={search.isPending} disabled={!canSearch}>
                {!search.isPending && <Search className="size-4" aria-hidden="true" />}
                {t.search.submit}
              </Button>
            </div>
          </form>
        </Card>

        <div aria-live="polite">
          {search.isError ? (
            <ErrorNote error={search.error} onRetry={() => search.mutate()} />
          ) : search.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : search.data && search.data.length === 0 ? (
            <EmptyState
              icon={<SearchX className="size-6" aria-hidden="true" />}
              title={t.search.noResults}
            />
          ) : search.data ? (
            <>
              <p className="mb-2 text-sm text-muted-foreground">
                <span className="nums font-semibold text-foreground">{n(search.data.length)}</span>{" "}
                {t.units.results}
              </p>
              <AnimatedList>
                {search.data.map((hit) => (
                  <div
                    key={`${hit.record_id}-${hit.chunk_index}`}
                    className="mb-2 rounded-xl border bg-card px-4 py-3"
                  >
                    <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                      <span className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <RecordLabel label={hit.label} />
                        {hit.source_name || t.results.deletedSource}
                      </span>
                      <span className="flex items-center gap-3">
                        {hit.vector_score !== null && (
                          <span className="nums text-xs text-muted-foreground">
                            {t.results.firstStage(pct(hit.vector_score))}
                          </span>
                        )}
                        <StatusBadge status={statusOf(hit.score)} />
                        <ScoreMeter score={hit.score} status={statusOf(hit.score)} />
                      </span>
                    </div>
                    <p dir="auto" className="whitespace-pre-wrap break-words text-sm">
                      {hit.text}
                    </p>
                  </div>
                ))}
              </AnimatedList>
            </>
          ) : null}
        </div>
      </div>

      <IndexStatusCard repo={repo} />
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Plus, TriangleAlert } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatedDialogContent } from "@/components/motion";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Button,
  EmptyState,
  ErrorNote,
  Field,
  PageHeader,
  Skeleton,
  TextArea,
  TextInput,
} from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type { Repo } from "@/lib/types";

function CreateRepoDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [touched, setTouched] = React.useState(false);

  const create = useMutation({
    mutationFn: () =>
      api.createRepo({ name: name.trim(), description: description.trim(), config: meta.data!.defaults }),
    onSuccess: (repo) => {
      queryClient.invalidateQueries({ queryKey: ["repos"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/repos/${repo.id}?tab=settings`);
    },
  });

  const nameError = touched && !name.trim() ? t.errors.name_required : undefined;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (name.trim() && meta.data && !create.isPending) create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !create.isPending && onOpenChange(next)}>
      <AnimatedDialogContent closeLabel={t.common.close}>
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>{t.repos.createTitle}</DialogTitle>
            <DialogDescription>{t.repos.createHint}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field label={t.common.name} error={nameError}>
              {(ids) => (
                <TextInput
                  {...ids}
                  autoFocus
                  value={name}
                  maxLength={200}
                  placeholder={t.repos.namePlaceholder}
                  aria-invalid={nameError ? true : undefined}
                  onChange={(e) => setName(e.target.value)}
                />
              )}
            </Field>
            <Field label={t.common.description}>
              {(ids) => (
                <TextArea
                  {...ids}
                  rows={3}
                  value={description}
                  placeholder={t.repos.descriptionPlaceholder}
                  onChange={(e) => setDescription(e.target.value)}
                />
              )}
            </Field>
            {create.isError && <ErrorNote error={create.error} />}
            {meta.isError && <ErrorNote error={meta.error} onRetry={() => meta.refetch()} />}
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              {t.common.cancel}
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!meta.data}>
              {t.common.create}
            </Button>
          </DialogFooter>
        </form>
      </AnimatedDialogContent>
    </Dialog>
  );
}

function RepoCard({ repo }: { repo: Repo }) {
  const { t, n } = useI18n();
  const facts = [
    [repo.source_count, t.units.sources],
    [repo.record_count, t.units.records],
    [repo.chunk_count, t.units.chunks],
  ] as const;
  return (
    <Link
      to={`/repos/${repo.id}`}
      aria-label={t.repos.open(repo.name)}
      className="hud-panel hud-tilt group flex h-full flex-col rounded-2xl border p-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 break-words text-lg font-semibold group-hover:text-primary">
          {repo.name}
        </h2>
        {repo.needs_reindex && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-sim-soft px-2 py-0.5 text-xs font-semibold text-sim">
            <TriangleAlert className="size-3" aria-hidden="true" />
            {t.repos.needsReindex}
          </span>
        )}
      </div>
      {repo.description && (
        <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{repo.description}</p>
      )}
      <p dir="ltr" className="mt-3 break-all text-start text-xs text-muted-foreground">
        {repo.config.embedding.model}
      </p>
      <dl className="mt-auto grid grid-cols-3 gap-2 pt-4 text-center">
        {facts.map(([value, unit]) => (
          <div key={unit} className="rounded-lg bg-muted px-1 py-2">
            <dt className="sr-only">{unit}</dt>
            <dd>
              <span className="nums block font-semibold">{n(value)}</span>
              <span className="text-xs text-muted-foreground">{unit}</span>
            </dd>
          </div>
        ))}
      </dl>
    </Link>
  );
}

export function ReposPage() {
  const { t } = useI18n();
  const [open, setOpen] = React.useState(false);
  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  const createButton = (
    <Button onClick={() => setOpen(true)}>
      <Plus className="size-4" aria-hidden="true" />
      {t.repos.create}
    </Button>
  );

  return (
    <>
      <PageHeader title={t.repos.title} subtitle={t.repos.subtitle} actions={createButton} />
      {repos.isError ? (
        <ErrorNote error={repos.error} onRetry={() => repos.refetch()} />
      ) : !repos.data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : repos.data.length === 0 ? (
        <EmptyState
          icon={<Database className="size-6" aria-hidden="true" />}
          title={t.repos.emptyTitle}
          body={t.repos.emptyBody}
          action={createButton}
        />
      ) : (
        <div className="hud-stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {repos.data.map((repo) => (
            <RepoCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}
      {open && <CreateRepoDialog open={open} onOpenChange={setOpen} />}
    </>
  );
}

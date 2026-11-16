import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Layers, Pencil, Plus, Trash2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import * as React from "react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Button,
  EmptyState,
  ErrorNote,
  Field,
  Select,
  Skeleton,
  TextArea,
} from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { motionTokens, transitions } from "@/lib/motion";
import type { Chunk, RecordChunks, Repo } from "@/lib/types";

const PAGE_SIZE = 20;
const MORE_CHUNKS = 50;
const MAX_CHUNK_CHARS = 20000;
const ALL = "all";

/** The text box shared by editing a chunk and adding one. */
function ChunkForm({
  initial,
  hint,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  initial: string;
  hint: string;
  pending: boolean;
  error: unknown;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  const { t, n } = useI18n();
  const [draft, setDraft] = React.useState(initial);
  const trimmed = draft.trim();
  const canSave = trimmed !== "" && trimmed !== initial;
  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    if (canSave && !pending) onSubmit(trimmed);
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <Field label={t.chunks.textLabel} hint={hint}>
        {(ids) => (
          <TextArea
            {...ids}
            autoFocus
            dir="auto"
            rows={Math.min(12, Math.max(3, Math.ceil(draft.length / 90)))}
            maxLength={MAX_CHUNK_CHARS}
            value={draft}
            disabled={pending}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !pending) {
                e.preventDefault();
                onCancel();
              } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                submit();
              }
            }}
          />
        )}
      </Field>
      {error ? <ErrorNote error={error} /> : null}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span className="me-auto text-xs text-muted-foreground">
          <span className="nums">{n(draft.length)}</span> {t.units.chars}
        </span>
        <Button variant="secondary" size="sm" disabled={pending} onClick={onCancel}>
          {t.common.cancel}
        </Button>
        <Button type="submit" size="sm" loading={pending} disabled={!canSave}>
          {t.common.save}
        </Button>
      </div>
    </form>
  );
}

function ChunkItem({
  recordId,
  chunk,
  onSaved,
  onDelete,
}: {
  recordId: string;
  chunk: Chunk;
  onSaved: (chunk: Chunk) => void;
  onDelete: (chunk: Chunk) => void;
}) {
  const { t, n } = useI18n();
  const reduceMotion = useReducedMotion();
  const queryClient = useQueryClient();
  const [editing, setEditing] = React.useState(false);
  const editButton = React.useRef<HTMLButtonElement>(null);
  const label = n(chunk.chunk_index + 1);

  const close = () => {
    setEditing(false);
    // The edit button remounts with the read view; hand focus back to it.
    requestAnimationFrame(() => editButton.current?.focus());
  };

  const save = useMutation({
    mutationFn: (text: string) => api.updateChunk(recordId, chunk.id, text),
    onSuccess: (updated) => {
      onSaved(updated);
      queryClient.invalidateQueries({ queryKey: ["chunks"] });
      close();
    },
  });

  return (
    <motion.li
      layout={reduceMotion ? false : "position"}
      initial={{ opacity: 0, y: reduceMotion ? 0 : 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{
        opacity: 0,
        transition: reduceMotion
          ? { duration: 0.01 }
          : { duration: motionTokens.duration.fast, ease: motionTokens.ease.exit },
      }}
      transition={reduceMotion ? { duration: 0.01 } : transitions.fast}
      className="border-t px-4 py-3 first:border-t-0"
    >
      <div className="mb-1 flex min-h-8 items-center justify-between gap-3 text-xs text-muted-foreground">
        <span className="nums font-medium">{t.chunks.chunk(label)}</span>
        <span className="flex items-center gap-1">
          <span className="me-1">
            <span className="nums">{n(chunk.text.length)}</span> {t.units.chars}
          </span>
          {!editing && (
            <>
              <Button
                ref={editButton}
                variant="ghost"
                size="sm"
                aria-label={t.chunks.editLabel(label)}
                title={t.chunks.editLabel(label)}
                onClick={() => {
                  save.reset();
                  setEditing(true);
                }}
              >
                <Pencil className="size-4" aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                aria-label={t.chunks.deleteLabel(label)}
                title={t.chunks.deleteLabel(label)}
                onClick={() => onDelete(chunk)}
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </>
          )}
        </span>
      </div>

      {editing ? (
        <ChunkForm
          initial={chunk.text}
          hint={t.chunks.editHint}
          pending={save.isPending}
          error={save.error}
          onSubmit={(text) => save.mutate(text)}
          onCancel={close}
        />
      ) : (
        <p dir="auto" className="whitespace-pre-wrap break-words text-sm">
          {chunk.text}
        </p>
      )}
    </motion.li>
  );
}

function RecordCard({ record }: { record: RecordChunks }) {
  const { t, n } = useI18n();
  const queryClient = useQueryClient();
  // The server sends a record's first chunks; later ones are loaded on demand
  // and kept here, as are edits and deletions until the listing is refetched.
  const [synced, setSynced] = React.useState(record);
  const [chunks, setChunks] = React.useState(record.chunks);
  const [count, setCount] = React.useState(record.chunk_count);
  const [exhausted, setExhausted] = React.useState(false);
  const [target, setTarget] = React.useState<Chunk | null>(null);
  const [adding, setAdding] = React.useState(false);
  const addButton = React.useRef<HTMLButtonElement>(null);

  if (synced !== record) {
    // A refetch wins for the chunks it covers; chunks loaded past them stay.
    const last = record.chunks.length ? record.chunks[record.chunks.length - 1].chunk_index : -1;
    const ids = new Set(record.chunks.map((c) => c.id));
    setSynced(record);
    setChunks([
      ...record.chunks,
      ...chunks.filter((c) => c.chunk_index > last && !ids.has(c.id)),
    ]);
    setCount(record.chunk_count);
  }

  const more = useMutation({
    mutationFn: () => api.recordChunks(record.record_id, chunks.length, MORE_CHUNKS),
    onSuccess: (loaded) => {
      setChunks((current) => {
        const have = new Set(current.map((c) => c.id));
        return [...current, ...loaded.filter((c) => !have.has(c.id))];
      });
      if (loaded.length < MORE_CHUNKS) setExhausted(true);
    },
  });
  const hasMore = !exhausted && chunks.length > 0 && chunks.length < count;

  // The index changed size: the repo's chunk count is part of the listing's
  // query key, so refreshing the repo refetches the listing; other pages go stale.
  const indexChanged = () => {
    queryClient.invalidateQueries({ queryKey: ["chunks"], refetchType: "none" });
    for (const key of ["repo", "repos", "stats"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const closeAdd = () => {
    setAdding(false);
    requestAnimationFrame(() => addButton.current?.focus());
  };
  const add = useMutation({
    mutationFn: (text: string) => api.addChunk(record.record_id, text),
    onSuccess: (added) => {
      // The new chunk is the record's last: show it once the ones before it are on screen.
      if (chunks.length >= count) setChunks((current) => [...current, added]);
      setCount(added.chunk_index + 1);
      closeAdd();
      indexChanged();
    },
  });

  const remove = useMutation({
    mutationFn: (chunk: Chunk) => api.deleteChunk(record.record_id, chunk.id),
    onSuccess: (_, removed) => {
      // The server closes the gap, so later chunks move up by one here too.
      setChunks((current) => {
        const at = current.find((c) => c.id === removed.id)?.chunk_index ?? removed.chunk_index;
        return current
          .filter((c) => c.id !== removed.id)
          .map((c) => (c.chunk_index > at ? { ...c, chunk_index: c.chunk_index - 1 } : c));
      });
      setCount((current) => Math.max(0, current - 1));
      setTarget(null);
      indexChanged();
    },
  });

  return (
    <li className="rounded-xl border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b bg-muted/60 px-4 py-2 text-xs text-muted-foreground">
        <span className="min-w-0 break-words">
          <span className="font-medium text-foreground">
            {record.source_name || t.results.deletedSource}
          </span>
          <span aria-hidden="true"> · </span>
          <span className="nums">{t.chunks.row(n(record.ordinal))}</span>
        </span>
        <span>
          <span className="nums">
            {chunks.length < count ? t.chunks.shown(n(chunks.length), n(count)) : n(chunks.length)}
          </span>{" "}
          {t.units.chunks}
        </span>
      </div>

      {chunks.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">{t.chunks.noChunks}</p>
      ) : (
        <ol>
          {/* Chunks already on screen do not animate in; later ones do. */}
          <AnimatePresence initial={false}>
            {chunks.map((chunk) => (
              <ChunkItem
                key={chunk.id}
                recordId={record.record_id}
                chunk={chunk}
                onSaved={(updated) =>
                  setChunks((current) => current.map((c) => (c.id === updated.id ? updated : c)))
                }
                onDelete={(c) => {
                  remove.reset();
                  setTarget(c);
                }}
              />
            ))}
          </AnimatePresence>
        </ol>
      )}

      <div className="space-y-2 border-t px-4 py-2.5">
        {more.isError && <ErrorNote error={more.error} />}
        {adding ? (
          <ChunkForm
            initial=""
            hint={t.chunks.addHint}
            pending={add.isPending}
            error={add.error}
            onSubmit={(text) => add.mutate(text)}
            onCancel={closeAdd}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {(hasMore || more.isError) && (
              <Button
                variant="ghost"
                size="sm"
                loading={more.isPending}
                onClick={() => more.mutate()}
              >
                {!more.isPending && <ChevronDown className="size-4" aria-hidden="true" />}
                {t.chunks.showMore}
              </Button>
            )}
            <Button
              ref={addButton}
              variant="ghost"
              size="sm"
              onClick={() => {
                add.reset();
                setAdding(true);
              }}
            >
              <Plus className="size-4" aria-hidden="true" />
              {t.chunks.add}
            </Button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => !open && setTarget(null)}
        title={t.chunks.deleteTitle}
        body={target ? t.chunks.deleteBody(n(target.chunk_index + 1)) : ""}
        pending={remove.isPending}
        error={remove.error}
        onConfirm={() => target && remove.mutate(target)}
      />
    </li>
  );
}

/** What is stored in the repo's index, grouped by record; chunks can be edited or deleted. */
export function ChunksPanel({ repo }: { repo: Repo }) {
  const { t, n } = useI18n();
  const [sourceId, setSourceId] = React.useState(ALL);
  const [page, setPage] = React.useState(1);

  const sources = useQuery({ queryKey: ["sources", repo.id], queryFn: () => api.sources(repo.id) });
  const indexed = (sources.data ?? []).filter((s) => s.indexed);
  // A source deleted elsewhere falls back to "all" instead of an empty filter.
  const activeSource = indexed.some((s) => s.id === sourceId) ? sourceId : ALL;

  const chunks = useQuery({
    // chunk_count changes whenever the index does, which refreshes the listing.
    queryKey: ["chunks", repo.id, activeSource, page, repo.chunk_count],
    queryFn: () => api.chunks(repo.id, activeSource === ALL ? null : activeSource, page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  });

  if (chunks.isError) return <ErrorNote error={chunks.error} onRetry={() => chunks.refetch()} />;
  if (!chunks.data) {
    return (
      <div className="space-y-3" role="status" aria-label={t.common.loading}>
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
    );
  }

  const data = chunks.data;
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  if (data.total === 0 && activeSource === ALL) {
    return (
      <EmptyState
        icon={<Layers className="size-6" aria-hidden="true" />}
        title={t.chunks.empty}
        body={t.chunks.emptyBody}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Field label={t.chunks.source} className="w-full sm:w-72">
          {(ids) => (
            <Select
              {...ids}
              value={activeSource}
              onValueChange={(value) => {
                setSourceId(value);
                setPage(1);
              }}
              options={[
                { value: ALL, label: t.chunks.allSources },
                ...indexed.map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
          )}
        </Field>
        <p className="text-sm text-muted-foreground">
          <span className="nums font-semibold text-foreground">{n(data.total)}</span>{" "}
          {t.units.records}
          {activeSource === ALL && (
            <>
              <span aria-hidden="true"> · </span>
              <span className="nums font-semibold text-foreground">{n(repo.chunk_count)}</span>{" "}
              {t.units.chunks}
            </>
          )}
        </p>
      </div>

      <ul
        aria-busy={chunks.isPlaceholderData || undefined}
        className={cn("space-y-3 transition-opacity", chunks.isPlaceholderData && "opacity-60")}
      >
        {data.items.map((record) => (
          <RecordCard key={record.record_id} record={record} />
        ))}
      </ul>

      {pages > 1 && (
        <nav className="flex items-center justify-center gap-3" aria-label={t.chunks.pages}>
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            {t.common.previous}
          </Button>
          <span className="nums text-sm text-muted-foreground">
            {t.common.page(n(page), n(pages))}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            {t.common.next}
          </Button>
        </nav>
      )}
    </div>
  );
}

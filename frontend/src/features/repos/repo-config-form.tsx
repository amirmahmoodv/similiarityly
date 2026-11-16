import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import * as React from "react";
import { NumericInput } from "@/components/ui/numeric-input";
import { Button, Card, ErrorNote, Field, Select, Switch, TextInput } from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fadeUpVariants } from "@/lib/motion";
import type { Repo, RepoConfig } from "@/lib/types";
import {
  configToDraft,
  draftToConfig,
  type ConfigDraft,
  type DraftError,
  type NumericField,
} from "@/lib/units";

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <h2 className="font-semibold">{title}</h2>
      <p className="mb-4 text-xs text-muted-foreground">{hint}</p>
      {children}
    </Card>
  );
}

/** Mirrors the backend's index signature: what forces a rebuild of stored vectors. */
function indexSignature(c: RepoConfig): string {
  const { provider, model, distance } = c.embedding;
  return JSON.stringify([provider, model, distance, c.chunking, c.normalization]);
}

export function RepoConfigForm({ repo }: { repo: Repo }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  const [draft, setDraft] = React.useState<ConfigDraft>(() => configToDraft(repo.config));
  const [errors, setErrors] = React.useState<DraftError[]>([]);
  const [savedAt, setSavedAt] = React.useState(0);

  const save = useMutation({
    mutationFn: (config: RepoConfig) => api.updateRepo(repo.id, { config }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["repo", repo.id], updated);
      queryClient.invalidateQueries({ queryKey: ["repos"] });
      // Thresholds are applied at read time, so cached results are now stale.
      queryClient.invalidateQueries({ queryKey: ["job-records"] });
      queryClient.invalidateQueries({ queryKey: ["job-summary"] });
      setDraft(configToDraft(updated.config));
      setSavedAt(Date.now());
    },
  });

  React.useEffect(() => {
    if (!savedAt) return;
    const timer = setTimeout(() => setSavedAt(0), 2500);
    return () => clearTimeout(timer);
  }, [savedAt]);

  const patch = <K extends "embedding" | "chunking" | "normalization" | "similarity">(
    key: K,
    value: Partial<ConfigDraft[K]>,
  ) => setDraft((d) => ({ ...d, [key]: { ...d[key], ...value } }));

  const numeric = (field: NumericField, label: string, unit: string, allowDecimal = false) => {
    const messages = t.config.errors as Record<string, string>;
    const extra =
      field === "overlap" && errors.includes("overlapTooLarge")
        ? "overlapTooLarge"
        : field === "duplicate_threshold" && errors.includes("thresholdOrder")
          ? "thresholdOrder"
          : null;
    const code = errors.includes(field) ? field : extra;
    return (
      <Field label={label} error={code ? messages[code] : undefined}>
        {(ids) => (
          <NumericInput
            {...ids}
            value={draft[field]}
            unit={unit}
            allowDecimal={allowDecimal}
            invalid={code !== null}
            onValueChange={(raw) => {
              setDraft((d) => ({ ...d, [field]: raw }));
              setErrors([]);
            }}
          />
        )}
      </Field>
    );
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const result = draftToConfig(draft);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors([]);
    save.mutate(result.config);
  };

  const parsed = draftToConfig(draft);
  const dirty =
    !parsed.ok || JSON.stringify(parsed.config) !== JSON.stringify(repo.config);
  const willReindex =
    parsed.ok &&
    repo.vector_size !== null &&
    indexSignature(parsed.config) !== indexSignature(repo.config);

  const providers = meta.data?.providers ?? [];
  const models = providers.find((p) => p.id === draft.embedding.provider)?.models ?? [];
  const others = (repos.data ?? []).filter((r) => r.id !== repo.id);
  const chunked = draft.chunking.strategy !== "record";
  const listId = React.useId();
  const rerankListId = React.useId();
  const rerankOn = draft.similarity.rerank !== "none";

  const toggles = [
    ["unify_chars", t.config.unifyChars],
    ["remove_diacritics", t.config.removeDiacritics],
    ["normalize_digits", t.config.normalizeDigits],
    ["lowercase", t.config.lowercase],
    ["strip_punctuation", t.config.stripPunctuation],
    ["collapse_whitespace", t.config.collapseWhitespace],
  ] as const;

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Section title={t.config.embedding} hint={t.config.embeddingHint}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.config.provider}>
              {(ids) => (
                <Select
                  {...ids}
                  value={draft.embedding.provider}
                  onValueChange={(provider) => {
                    const first = providers.find((p) => p.id === provider)?.models[0];
                    patch("embedding", { provider, model: first ?? draft.embedding.model });
                  }}
                  options={(["fastembed", "openai", "hash"] as const).map((id) => {
                    const available = providers.find((p) => p.id === id)?.available ?? true;
                    return {
                      value: id,
                      label: available
                        ? t.config.providers[id]
                        : `${t.config.providers[id]} — ${t.config.unavailable}`,
                      // Keep the current choice selectable even if it became unavailable.
                      disabled: !available && id !== draft.embedding.provider,
                    };
                  })}
                />
              )}
            </Field>
            <Field label={t.config.distance}>
              {(ids) => (
                <Select
                  {...ids}
                  value={draft.embedding.distance}
                  onValueChange={(distance) => patch("embedding", { distance })}
                  options={(["cosine", "dot", "euclid"] as const).map((value) => ({
                    value,
                    label: t.config.distances[value],
                  }))}
                />
              )}
            </Field>
            <Field label={t.config.model} className="sm:col-span-2">
              {(ids) => (
                <>
                  <TextInput
                    {...ids}
                    dir="ltr"
                    list={listId}
                    value={draft.embedding.model}
                    onChange={(e) => patch("embedding", { model: e.target.value })}
                  />
                  <datalist id={listId}>
                    {models.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
            {numeric("batch_size", t.config.batchSize, t.units.records)}
          </div>
        </Section>

        <Section title={t.config.chunking} hint={t.config.chunkingHint}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.config.strategy} className="sm:col-span-2">
              {(ids) => (
                <Select
                  {...ids}
                  value={draft.chunking.strategy}
                  onValueChange={(strategy) => patch("chunking", { strategy })}
                  options={(["record", "sentence", "paragraph", "fixed"] as const).map((value) => ({
                    value,
                    label: t.config.strategies[value],
                  }))}
                />
              )}
            </Field>
            <div className={cn("contents", !chunked && "[&>*]:opacity-50")}>
              {numeric("chunk_size", t.config.chunkSize, t.units.chars)}
              {numeric("overlap", t.config.overlap, t.units.chars)}
            </div>
            {numeric("min_chars", t.config.minChars, t.units.chars)}
          </div>
        </Section>

        <Section title={t.config.normalization} hint={t.config.normalizationHint}>
          <div className="divide-y">
            {toggles.map(([key, label]) => (
              <Switch
                key={key}
                label={label}
                checked={draft.normalization[key]}
                onCheckedChange={(checked) => patch("normalization", { [key]: checked })}
              />
            ))}
          </div>
          <Field label={t.config.zwnj} className="mt-3">
            {(ids) => (
              <Select
                {...ids}
                value={draft.normalization.zwnj}
                onValueChange={(zwnj) => patch("normalization", { zwnj })}
                options={(["keep", "space", "remove"] as const).map((value) => ({
                  value,
                  label: t.config.zwnjModes[value],
                }))}
              />
            )}
          </Field>
        </Section>

        <Section title={t.config.similarity} hint={t.config.similarityHint}>
          <div className="grid gap-4 sm:grid-cols-2">
            {numeric("similar_threshold", t.config.similarThreshold, t.units.percent, true)}
            {numeric("duplicate_threshold", t.config.duplicateThreshold, t.units.percent, true)}
            {numeric("top_k", t.config.topK, t.units.results)}
            <Field label={t.config.aggregation}>
              {(ids) => (
                <Select
                  {...ids}
                  value={draft.similarity.aggregation}
                  onValueChange={(aggregation) => patch("similarity", { aggregation })}
                  options={(["max", "mean"] as const).map((value) => ({
                    value,
                    label: t.config.aggregations[value],
                  }))}
                />
              )}
            </Field>
            <Field
              label={t.config.rerank}
              hint={rerankOn ? t.config.rerankHint : undefined}
              className="sm:col-span-2"
            >
              {(ids) => (
                <Select
                  {...ids}
                  value={draft.similarity.rerank}
                  onValueChange={(rerank) => patch("similarity", { rerank })}
                  options={(["none", "cross_encoder"] as const).map((value) => {
                    const available = value === "none" || (meta.data?.rerankers.available ?? true);
                    return {
                      value,
                      label: available
                        ? t.config.reranks[value]
                        : `${t.config.reranks[value]} — ${t.config.unavailable}`,
                      disabled: !available && value !== draft.similarity.rerank,
                    };
                  })}
                />
              )}
            </Field>
            <AnimatePresence initial={false}>
              {rerankOn && (
                <motion.div
                  key="rerank-model"
                  variants={fadeUpVariants}
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                  className="sm:col-span-2"
                >
                  <Field label={t.config.rerankModel}>
                    {(ids) => (
                      <>
                        <TextInput
                          {...ids}
                          dir="ltr"
                          list={rerankListId}
                          value={draft.similarity.rerank_model}
                          onChange={(e) => patch("similarity", { rerank_model: e.target.value })}
                        />
                        <datalist id={rerankListId}>
                          {(meta.data?.rerankers.models ?? []).map((m) => (
                            <option key={m} value={m} />
                          ))}
                        </datalist>
                      </>
                    )}
                  </Field>
                </motion.div>
              )}
            </AnimatePresence>
            <Field label={t.config.scope} className="sm:col-span-2">
              {(ids) => (
                <Select
                  {...ids}
                  value={draft.similarity.scope}
                  onValueChange={(scope) => patch("similarity", { scope })}
                  options={(["self", "selected", "all"] as const).map((value) => ({
                    value,
                    label: t.config.scopes[value],
                  }))}
                />
              )}
            </Field>
            {draft.similarity.scope === "selected" && (
              <fieldset className="sm:col-span-2">
                <legend className="mb-1.5 text-sm font-medium">{t.config.targets}</legend>
                {others.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t.config.noOtherRepos}</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {others.map((other) => {
                      const ids = draft.similarity.target_repo_ids;
                      const on = ids.includes(other.id);
                      return (
                        <button
                          key={other.id}
                          type="button"
                          aria-pressed={on}
                          onClick={() =>
                            patch("similarity", {
                              target_repo_ids: on
                                ? ids.filter((id) => id !== other.id)
                                : [...ids, other.id],
                            })
                          }
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                            on ? "border-primary bg-accent text-primary" : "hover:bg-muted",
                          )}
                        >
                          {on && <Check className="size-3.5" aria-hidden="true" />}
                          {other.name}
                        </button>
                      );
                    })}
                  </div>
                )}
              </fieldset>
            )}
          </div>
        </Section>
      </div>

      {save.isError && <ErrorNote error={save.error} />}

      <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card/95 px-4 py-3 shadow-md backdrop-blur">
        <div className="min-h-6 text-sm" aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            {willReindex ? (
              <motion.span
                key="reindex"
                variants={fadeUpVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="flex items-center gap-2 text-sim"
              >
                <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
                {t.config.willReindex}
              </motion.span>
            ) : savedAt ? (
              <motion.span
                key="saved"
                variants={fadeUpVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="flex items-center gap-2 text-uniq"
              >
                <Check className="size-4" aria-hidden="true" />
                {t.common.saved}
              </motion.span>
            ) : null}
          </AnimatePresence>
        </div>
        <Button type="submit" loading={save.isPending} disabled={!dirty}>
          {t.common.save}
        </Button>
      </div>
    </form>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, CircleCheck, CircleX, PlugZap, TriangleAlert, Waypoints } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import * as React from "react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Button,
  Card,
  ErrorNote,
  Field,
  PageHeader,
  Select,
  Skeleton,
  TextInput,
} from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fadeUpVariants } from "@/lib/motion";
import type {
  AppSettings,
  ConnectionTest,
  LLMProvider,
  LLMSettingsInput,
  QdrantSettingsInput,
} from "@/lib/types";

const DEFAULT_BASE_URL: Record<LLMProvider, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com",
};

// ---- Shared pieces ----------------------------------------------------------

function SectionCard({
  icon,
  title,
  hint,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <div className="mb-5 flex items-start gap-3">
        <div className="rounded-xl bg-accent p-2 text-primary">{icon}</div>
        <div className="min-w-0">
          <h2 className="font-semibold">{title}</h2>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
      </div>
      {children}
    </Card>
  );
}

/** Write-only key: the saved value never comes back from the API. */
type KeyDraft = { value: string; clear: boolean };

/** null keeps the saved key, "" clears it. */
function keyPayload(key: KeyDraft): string | null {
  return key.clear ? "" : key.value.trim() || null;
}

function ApiKeyField({
  saved,
  draft,
  onChange,
}: {
  saved: boolean;
  draft: KeyDraft;
  onChange: (draft: KeyDraft) => void;
}) {
  const { t } = useI18n();
  return (
    <Field
      label={t.settings.apiKey}
      hint={
        draft.clear ? t.settings.keyWillClear : saved ? t.settings.apiKeySaved : t.settings.apiKeyNone
      }
    >
      {(ids) => (
        <div className="flex gap-2">
          <TextInput
            {...ids}
            type="password"
            dir="ltr"
            // "off" is ignored for password fields: Chrome would autofill the user's saved
            // login here (and a username into the URL field above it). "new-password" stops
            // that; the data-* attributes do the same for common password managers.
            autoComplete="new-password"
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            spellCheck={false}
            disabled={draft.clear}
            placeholder={saved && !draft.clear ? "••••••••" : ""}
            value={draft.value}
            onChange={(e) => onChange({ value: e.target.value, clear: false })}
          />
          {saved && (
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0"
              onClick={() => onChange({ value: "", clear: !draft.clear })}
            >
              {draft.clear ? t.settings.undo : t.settings.clearKey}
            </Button>
          )}
        </div>
      )}
    </Field>
  );
}

function TestResult({ result, children }: { result: ConnectionTest; children?: React.ReactNode }) {
  const { t, n } = useI18n();
  const errors = t.settings.errors as Record<string, string>;
  return (
    <motion.div
      variants={fadeUpVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      role="status"
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        result.ok ? "border-uniq/40 bg-uniq-soft" : "border-destructive/40 bg-dup-soft",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span
          className={cn(
            "flex items-center gap-2 font-semibold",
            result.ok ? "text-uniq" : "text-destructive",
          )}
        >
          {result.ok ? (
            <CircleCheck className="size-4" aria-hidden="true" />
          ) : (
            <CircleX className="size-4" aria-hidden="true" />
          )}
          {result.ok ? t.settings.ok : t.settings.failed}
        </span>
        {result.latency_ms > 0 && (
          <span className="text-muted-foreground">
            {t.settings.latency}:{" "}
            <span className="nums text-foreground">
              {n(result.latency_ms)} {t.units.ms}
            </span>
          </span>
        )}
        {children}
      </div>
      {!result.ok && (
        <p className="mt-1.5">{errors[result.error ?? ""] ?? t.errors.unknown_error}</p>
      )}
      {result.detail && (
        <details className="mt-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t.settings.details}
          </summary>
          <pre dir="ltr" className="mt-1 whitespace-pre-wrap break-all text-start font-mono">
            {result.detail}
          </pre>
        </details>
      )}
    </motion.div>
  );
}

function SavedNote({ show }: { show: boolean }) {
  const { t } = useI18n();
  return (
    <span className="min-h-6 text-sm" aria-live="polite">
      <AnimatePresence initial={false}>
        {show && (
          <motion.span
            variants={fadeUpVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="flex items-center gap-2 text-uniq"
          >
            <Check className="size-4" aria-hidden="true" />
            {t.common.saved}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

function useFlash(): [boolean, () => void] {
  const [at, setAt] = React.useState(0);
  React.useEffect(() => {
    if (!at) return;
    const timer = setTimeout(() => setAt(0), 2500);
    return () => clearTimeout(timer);
  }, [at]);
  return [at > 0, () => setAt(Date.now())];
}

// ---- Qdrant -----------------------------------------------------------------

function QdrantSection({ settings }: { settings: AppSettings["qdrant"] }) {
  const { t, n } = useI18n();
  const queryClient = useQueryClient();
  const [mode, setMode] = React.useState<"server" | "embedded">(
    settings.mode === "embedded" ? "embedded" : "server",
  );
  const [url, setUrl] = React.useState(settings.url || "http://localhost:6333");
  const [key, setKey] = React.useState<KeyDraft>({ value: "", clear: false });
  const [confirming, setConfirming] = React.useState(false);
  const [saved, flashSaved] = useFlash();

  const input: QdrantSettingsInput = { mode, url: url.trim(), api_key: keyPayload(key) };
  const urlInvalid = mode === "server" && !/^https?:\/\/\S+$/.test(input.url);

  const test = useMutation({ mutationFn: api.testQdrant });
  const save = useMutation({
    mutationFn: api.saveQdrant,
    onSuccess: (next) => {
      queryClient.setQueryData(["settings"], next);
      // Every repo, job and stat now comes from a different store.
      queryClient.invalidateQueries();
      setKey({ value: "", clear: false });
      setConfirming(false);
      flashSaved();
    },
  });

  // A result describes the values it was run with; drop it once they change.
  const resetFeedback = () => {
    test.reset();
    save.reset();
  };

  const targetChanged =
    mode !== settings.mode || (mode === "server" && input.url !== settings.url);
  const dirty = targetChanged || key.clear || key.value.trim() !== "";

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (urlInvalid || !dirty) return;
    if (targetChanged) setConfirming(true);
    else save.mutate(input);
  };

  return (
    <SectionCard
      icon={<Waypoints className="size-5" aria-hidden="true" />}
      title={t.settings.qdrant.title}
      hint={t.settings.qdrant.hint}
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        {settings.mode === "memory" && (
          <p className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {t.settings.qdrant.memoryNote}
          </p>
        )}
        <Field label={t.settings.qdrant.mode}>
          {(ids) => (
            <Select
              {...ids}
              value={mode}
              onValueChange={(next) => {
                setMode(next);
                resetFeedback();
              }}
              options={(["server", "embedded"] as const).map((value) => ({
                value,
                label: t.settings.qdrant.modes[value],
              }))}
            />
          )}
        </Field>

        <AnimatePresence initial={false}>
          {mode === "server" && (
            <motion.div
              key="server-fields"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-4 overflow-hidden p-0.5"
            >
              <Field
                label={t.settings.qdrant.url}
                error={urlInvalid && input.url !== "" ? t.errors.validation_error : undefined}
              >
                {(ids) => (
                  <TextInput
                    {...ids}
                    dir="ltr"
                    inputMode="url"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="http://localhost:6333"
                    aria-invalid={urlInvalid || undefined}
                    value={url}
                    onChange={(e) => {
                      setUrl(e.target.value);
                      resetFeedback();
                    }}
                  />
                )}
              </Field>
              <ApiKeyField
                saved={settings.api_key_set}
                draft={key}
                onChange={(next) => {
                  setKey(next);
                  resetFeedback();
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence mode="wait" initial={false}>
          {test.data && (
            <TestResult key="result" result={test.data}>
              {test.data.version && (
                <span className="text-muted-foreground">
                  {t.settings.qdrant.version}:{" "}
                  <bdi dir="ltr" className="text-foreground">
                    {test.data.version}
                  </bdi>
                </span>
              )}
              {test.data.collections !== null && (
                <span className="text-muted-foreground">
                  {t.settings.qdrant.collections}:{" "}
                  <span className="nums text-foreground">
                    {n(test.data.collections)} {t.units.collections}
                  </span>
                </span>
              )}
            </TestResult>
          )}
        </AnimatePresence>
        {test.isError && <ErrorNote error={test.error} />}
        {save.isError && !confirming && <ErrorNote error={save.error} />}

        {targetChanged && (
          <p className="flex items-start gap-2 text-xs text-sim">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {t.settings.qdrant.switchWarning}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-3 border-t pt-4">
          <span className="me-auto">
            <SavedNote show={saved} />
          </span>
          {mode === "server" && (
            <Button
              variant="secondary"
              loading={test.isPending}
              disabled={urlInvalid}
              onClick={() => test.mutate(input)}
            >
              <PlugZap className="size-4" aria-hidden="true" />
              {t.settings.test}
            </Button>
          )}
          <Button type="submit" loading={save.isPending && !confirming} disabled={urlInvalid || !dirty}>
            {t.common.save}
          </Button>
        </div>
      </form>

      <ConfirmDialog
        open={confirming}
        onOpenChange={(open) => {
          setConfirming(open);
          if (!open) save.reset();
        }}
        title={t.settings.qdrant.confirmTitle}
        body={t.settings.qdrant.confirmBody}
        confirmLabel={t.settings.qdrant.confirm}
        variant="primary"
        pending={save.isPending}
        error={save.error ?? undefined}
        onConfirm={() => save.mutate(input)}
      />
    </SectionCard>
  );
}

// ---- LLM --------------------------------------------------------------------

function LLMSection({ settings }: { settings: AppSettings["llm"] }) {
  const { t, n } = useI18n();
  const queryClient = useQueryClient();
  const [provider, setProvider] = React.useState<LLMProvider>(settings.provider);
  const [baseUrl, setBaseUrl] = React.useState(settings.base_url);
  const [model, setModel] = React.useState(settings.model);
  const [key, setKey] = React.useState<KeyDraft>({ value: "", clear: false });
  const [saved, flashSaved] = useFlash();
  const [models, setModels] = React.useState<string[]>([]);
  const listId = React.useId();

  const input: LLMSettingsInput = {
    provider,
    base_url: baseUrl.trim(),
    model: model.trim(),
    api_key: keyPayload(key),
  };
  const urlInvalid = input.base_url !== "" && !/^https?:\/\/\S+$/.test(input.base_url);

  const test = useMutation({
    mutationFn: api.testLLM,
    onSuccess: (result) => {
      if (result.ok) setModels(result.models);
    },
  });
  const save = useMutation({
    mutationFn: api.saveLLM,
    onSuccess: (next) => {
      queryClient.setQueryData(["settings"], next);
      setKey({ value: "", clear: false });
      flashSaved();
    },
  });

  const resetFeedback = () => {
    test.reset();
    save.reset();
  };

  const dirty =
    provider !== settings.provider ||
    input.base_url !== settings.base_url ||
    input.model !== settings.model ||
    key.clear ||
    key.value.trim() !== "";

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!urlInvalid && dirty) save.mutate(input);
  };

  return (
    <SectionCard
      icon={<Bot className="size-5" aria-hidden="true" />}
      title={t.settings.llm.title}
      hint={t.settings.llm.hint}
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field label={t.settings.llm.provider}>
          {(ids) => (
            <Select
              {...ids}
              value={provider}
              onValueChange={(next) => {
                setProvider(next);
                setModels([]);
                resetFeedback();
              }}
              options={(["openai", "anthropic"] as const).map((value) => ({
                value,
                label: t.settings.llm.providers[value],
              }))}
            />
          )}
        </Field>
        <Field
          label={t.settings.llm.baseUrl}
          hint={t.settings.llm.baseUrlHint}
          error={urlInvalid ? t.errors.validation_error : undefined}
        >
          {(ids) => (
            <TextInput
              {...ids}
              dir="ltr"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              placeholder={DEFAULT_BASE_URL[provider]}
              aria-invalid={urlInvalid || undefined}
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.target.value);
                resetFeedback();
              }}
            />
          )}
        </Field>
        <ApiKeyField
          saved={settings.api_key_set}
          draft={key}
          onChange={(next) => {
            setKey(next);
            resetFeedback();
          }}
        />
        <Field label={t.settings.llm.model}>
          {(ids) => (
            <>
              <TextInput
                {...ids}
                dir="ltr"
                list={listId}
                autoComplete="off"
                spellCheck={false}
                placeholder={provider === "anthropic" ? "claude-opus-5-5" : "gpt-…"}
                value={model}
                onChange={(e) => {
                  setModel(e.target.value);
                  save.reset();
                }}
              />
              <datalist id={listId}>
                {models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </>
          )}
        </Field>

        <AnimatePresence mode="wait" initial={false}>
          {test.data && (
            <TestResult key="result" result={test.data}>
              {test.data.ok && (
                <span className="text-muted-foreground">
                  {t.settings.llm.models}:{" "}
                  <span className="nums text-foreground">
                    {n(test.data.models.length)} {t.units.models}
                  </span>
                </span>
              )}
              {test.data.model_found !== null && (
                <span
                  className={cn(
                    "flex items-center gap-1.5 basis-full",
                    test.data.model_found ? "text-uniq" : "text-sim",
                  )}
                >
                  {test.data.model_found ? (
                    <Check className="size-3.5" aria-hidden="true" />
                  ) : (
                    <TriangleAlert className="size-3.5" aria-hidden="true" />
                  )}
                  {test.data.model_found ? t.settings.llm.modelFound : t.settings.llm.modelMissing}
                </span>
              )}
            </TestResult>
          )}
        </AnimatePresence>
        {test.isError && <ErrorNote error={test.error} />}
        {save.isError && <ErrorNote error={save.error} />}

        <div className="flex flex-wrap items-center justify-end gap-3 border-t pt-4">
          <span className="me-auto">
            <SavedNote show={saved} />
          </span>
          <Button
            variant="secondary"
            loading={test.isPending}
            disabled={urlInvalid}
            onClick={() => test.mutate(input)}
          >
            <PlugZap className="size-4" aria-hidden="true" />
            {t.settings.test}
          </Button>
          <Button type="submit" loading={save.isPending} disabled={urlInvalid || !dirty}>
            {t.common.save}
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}

// ---- Page -------------------------------------------------------------------

export function SettingsPage() {
  const { t } = useI18n();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  return (
    <>
      <PageHeader title={t.settings.title} subtitle={t.settings.subtitle} />
      {settings.isError ? (
        <ErrorNote error={settings.error} onRetry={() => settings.refetch()} />
      ) : settings.data ? (
        <>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <QdrantSection settings={settings.data.qdrant} />
            <LLMSection settings={settings.data.llm} />
          </div>
          <p className="mt-4 text-xs text-muted-foreground">{t.settings.envNote}</p>
        </>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-80 rounded-2xl" />
          <Skeleton className="h-80 rounded-2xl" />
        </div>
      )}
    </>
  );
}

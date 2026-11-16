import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, FileUp, Play, X } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router-dom";
import { AnimatedTabs } from "@/components/motion";
import {
  Button,
  Card,
  ErrorNote,
  Field,
  Select,
  Skeleton,
  Switch,
  TextArea,
  TextInput,
} from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api, type IngestInput } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { IngestMode, Repo } from "@/lib/types";

type InputTab = "file" | "list" | "text";
const MODES: IngestMode[] = ["check_and_index", "check_only", "index_only"];
const ACCEPT = ".xlsx,.xlsm,.csv,.tsv,.txt,.md,.docx,.pdf";

function countRecords(text: string, split: "lines" | "paragraphs" | "whole"): number {
  if (!text.trim()) return 0;
  if (split === "whole") return 1;
  const parts = split === "lines" ? text.split("\n") : text.split(/\n\s*\n/);
  return parts.filter((p) => p.trim()).length;
}

export function IngestPanel({ repo }: { repo: Repo }) {
  const { t, n } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [tab, setTab] = React.useState<InputTab>("file");
  const [mode, setMode] = React.useState<IngestMode>("check_and_index");
  const [name, setName] = React.useState("");
  const [listText, setListText] = React.useState("");
  const [freeText, setFreeText] = React.useState("");
  const [split, setSplit] = React.useState<"whole" | "paragraphs">("whole");
  const [file, setFile] = React.useState<File | null>(null);
  const [sheet, setSheet] = React.useState<string | undefined>();
  const [hasHeader, setHasHeader] = React.useState(true);
  const [columns, setColumns] = React.useState<string[]>([]);
  const fileInput = React.useRef<HTMLInputElement>(null);

  const preview = useQuery({
    queryKey: ["preview", file?.name, file?.size, file?.lastModified, sheet, hasHeader],
    queryFn: () => api.preview(file!, sheet, hasHeader),
    enabled: file !== null,
    staleTime: Infinity,
    retry: false,
  });

  const start = useMutation({
    mutationFn: (input: IngestInput) => api.ingest(repo.id, input),
    onSuccess: (job) => {
      for (const key of ["jobs", "stats", "sources", "repos", "repo"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      navigate(`/jobs/${job.id}`);
    },
  });

  const pickFile = (next: File | null) => {
    setFile(next);
    setSheet(undefined);
    setColumns([]);
    start.reset();
  };

  const detected =
    tab === "list"
      ? countRecords(listText, "lines")
      : tab === "text"
        ? countRecords(freeText, split)
        : preview.data?.kind === "tabular"
          ? preview.data.total_rows
          : preview.data
            ? 1
            : 0;
  const ready = tab === "file" ? file !== null && preview.isSuccess && detected > 0 : detected > 0;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready || start.isPending) return;
    const base = { mode, name: name.trim() };
    if (tab === "file") {
      start.mutate({
        ...base,
        kind: "file",
        file: file!,
        options: { sheet, has_header: hasHeader, text_columns: columns },
      });
    } else if (tab === "list") {
      start.mutate({ ...base, kind: "text", split: "lines", text: listText });
    } else {
      start.mutate({ ...base, kind: "text", split, text: freeText });
    }
  };

  const data = preview.data;

  return (
    <form onSubmit={submit} className="grid items-start gap-4 lg:grid-cols-[1fr_20rem]">
      <Card className="min-w-0 space-y-4">
        <AnimatedTabs
          label={t.ingest.inputLabel}
          value={tab}
          onValueChange={(v) => setTab(v as InputTab)}
          items={[
            { id: "file", label: t.ingest.file },
            { id: "list", label: t.ingest.list },
            { id: "text", label: t.ingest.text },
          ]}
        />

        {tab === "file" && (
          <div className="space-y-4">
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                pickFile(e.dataTransfer.files[0] ?? null);
              }}
              className="flex w-full flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center outline-none transition-colors hover:border-primary hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring"
            >
              <FileUp className="size-6 text-primary" aria-hidden="true" />
              <span className="break-all font-medium">
                {file ? file.name : t.ingest.chooseFile}
              </span>
              <span className="text-xs text-muted-foreground">
                {file ? t.ingest.changeFile : t.ingest.fileHint}
              </span>
            </button>

            {file && preview.isPending && (
              <div role="status" className="space-y-2">
                <span className="sr-only">{t.ingest.reading}</span>
                <Skeleton className="h-8" />
                <Skeleton className="h-24" />
              </div>
            )}
            {preview.isError && <ErrorNote error={preview.error} />}

            {data?.kind === "tabular" && (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  {data.sheets.length > 1 && (
                    <Field label={t.ingest.sheet}>
                      {(ids) => (
                        <Select
                          {...ids}
                          value={sheet ?? data.sheets[0]}
                          onValueChange={(v) => {
                            setSheet(v);
                            setColumns([]);
                          }}
                          options={data.sheets.map((s) => ({ value: s, label: s }))}
                        />
                      )}
                    </Field>
                  )}
                  <div className="self-end">
                    <Switch
                      label={t.ingest.hasHeader}
                      checked={hasHeader}
                      onCheckedChange={(v) => {
                        setHasHeader(v);
                        setColumns([]);
                      }}
                    />
                  </div>
                </div>

                <fieldset>
                  <legend className="text-sm font-medium">{t.ingest.columns}</legend>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                    <p className="text-xs text-muted-foreground">{t.ingest.columnsHint}</p>
                    {data.columns.length > 1 &&
                      (() => {
                        const all = data.columns.every((c) => columns.includes(c));
                        const Icon = all ? X : CheckCheck;
                        return (
                          <button
                            type="button"
                            onClick={() => setColumns(all ? [] : [...data.columns])}
                            className="hud-btn inline-flex shrink-0 items-center gap-1.5 rounded-full border border-primary/40 px-3 py-1 text-xs font-semibold text-primary outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <Icon className="size-3.5" aria-hidden="true" />
                            {all ? t.ingest.clearColumns : t.ingest.selectAllColumns}
                          </button>
                        );
                      })()}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {data.columns.map((column) => {
                      const on = columns.includes(column);
                      return (
                        <button
                          key={column}
                          type="button"
                          aria-pressed={on}
                          onClick={() =>
                            setColumns(on ? columns.filter((c) => c !== column) : [...columns, column])
                          }
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                            on ? "border-primary bg-accent text-primary" : "hover:bg-muted",
                          )}
                        >
                          {on && <Check className="size-3.5" aria-hidden="true" />}
                          {column}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>

                <div>
                  <div className="mb-1.5 text-sm font-medium">{t.ingest.preview}</div>
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted text-start">
                        <tr>
                          {data.columns.map((c) => (
                            <th
                              key={c}
                              scope="col"
                              className={cn(
                                "whitespace-nowrap px-3 py-2 text-start font-medium",
                                columns.includes(c) && "text-primary",
                              )}
                            >
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.rows.map((row, i) => (
                          <tr key={i} className="border-t">
                            {row.map((cell, j) => (
                              <td key={j} className="max-w-64 truncate px-3 py-1.5">
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}

            {data?.kind === "document" && (
              <div>
                <div className="mb-1.5 flex items-center justify-between text-sm">
                  <span className="font-medium">{t.ingest.preview}</span>
                  <span className="text-muted-foreground">
                    {t.ingest.documentChars}:{" "}
                    <span className="nums">{n(data.char_count)}</span> {t.units.chars}
                  </span>
                </div>
                <p className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border bg-muted/50 p-3 text-sm">
                  {data.excerpt}
                </p>
              </div>
            )}
          </div>
        )}

        {tab === "list" && (
          <Field label={t.ingest.list} hint={t.ingest.listHint}>
            {(ids) => (
              <TextArea
                {...ids}
                rows={10}
                dir="auto"
                value={listText}
                placeholder={t.ingest.listPlaceholder}
                onChange={(e) => setListText(e.target.value)}
              />
            )}
          </Field>
        )}

        {tab === "text" && (
          <div className="space-y-4">
            <Field label={t.ingest.text}>
              {(ids) => (
                <TextArea
                  {...ids}
                  rows={10}
                  dir="auto"
                  value={freeText}
                  placeholder={t.ingest.textPlaceholder}
                  onChange={(e) => setFreeText(e.target.value)}
                />
              )}
            </Field>
            <Field label={t.ingest.textSplit} className="max-w-xs">
              {(ids) => (
                <Select
                  {...ids}
                  value={split}
                  onValueChange={setSplit}
                  options={[
                    { value: "whole", label: t.ingest.splitWhole },
                    { value: "paragraphs", label: t.ingest.splitParagraphs },
                  ]}
                />
              )}
            </Field>
          </div>
        )}
      </Card>

      <Card className="space-y-4 lg:sticky lg:top-6">
        <Field label={t.ingest.sourceName}>
          {(ids) => (
            <TextInput
              {...ids}
              value={name}
              maxLength={300}
              placeholder={t.ingest.sourceNamePlaceholder}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>

        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">{t.mode.label}</legend>
          <div className="space-y-2">
            {MODES.map((m) => (
              <label
                key={m}
                className={cn(
                  "flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors",
                  "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                  mode === m ? "border-primary bg-accent/60" : "hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="ingest-mode"
                  className="mt-1.5 accent-(--primary)"
                  checked={mode === m}
                  onChange={() => setMode(m)}
                />
                <span>
                  <span className="block text-sm font-medium">{t.mode[m].title}</span>
                  <span className="block text-xs text-muted-foreground">{t.mode[m].hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex items-baseline justify-between text-sm">
          <span className="text-muted-foreground">{t.ingest.detected}</span>
          <span>
            <span className="nums font-semibold">{n(detected)}</span>{" "}
            <span className="text-muted-foreground">{t.units.records}</span>
          </span>
        </div>

        {start.isError && <ErrorNote error={start.error} />}
        {repo.needs_reindex && (
          <p role="note" className="text-sm text-sim">
            {t.ingest.blocked}
          </p>
        )}

        <Button
          type="submit"
          className="w-full"
          loading={start.isPending}
          disabled={!ready || repo.needs_reindex}
        >
          {!start.isPending && <Play className="size-4 rtl:-scale-x-100" aria-hidden="true" />}
          {start.isPending ? t.ingest.submitting : t.ingest.submit}
        </Button>
      </Card>
    </form>
  );
}

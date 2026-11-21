import { Columns3, Download, Rows3 } from "lucide-react";
import * as React from "react";
import { AnimatedDialogContent } from "@/components/motion";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { NumericInput } from "@/components/ui/numeric-input";
import { Button, ErrorNote, Field, Select } from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { api, type ExportLayout } from "@/lib/api";
import { cn } from "@/lib/cn";
import { rawToNumber } from "@/lib/format";
import type { RecordStatus } from "@/lib/types";

type StatusFilter = RecordStatus | "all";
const STATUSES: StatusFilter[] = ["all", "duplicate", "similar", "unique"];
const LAYOUTS = [
  { id: "wide", Icon: Columns3 },
  { id: "long", Icon: Rows3 },
] as const satisfies readonly { id: ExportLayout; Icon: React.ElementType }[];

/** Raw field text → a valid candidate count (the API takes 1..100), or null. */
function parseCandidateCount(raw: string): number | null {
  const value = rawToNumber(raw);
  return Number.isInteger(value) && value >= 1 && value <= 100 ? value : null;
}

/** Choose how a check is written to Excel: layout, candidates per record, which records. */
export function ExportDialog({
  jobId,
  initialStatus = "all",
  open,
  onOpenChange,
}: {
  jobId: string;
  /** The filter the page is showing, offered as the starting choice. */
  initialStatus?: StatusFilter;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t, locale } = useI18n();
  const d = t.results.exportDialog;
  const groupId = React.useId();
  const [layout, setLayout] = React.useState<ExportLayout>("wide");
  const [count, setCount] = React.useState("3");
  const [status, setStatus] = React.useState<StatusFilter>(initialStatus);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  // Opening starts from the page's current filter; layout and count are kept.
  const [wasOpen, setWasOpen] = React.useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setStatus(initialStatus);
      setError(null);
    }
  }

  const candidates = parseCandidateCount(count);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (candidates === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.exportXlsx(jobId, { layout, candidates, status, lang: locale });
      onOpenChange(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <AnimatedDialogContent closeLabel={t.common.close}>
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>{d.title}</DialogTitle>
            <DialogDescription>{d.hint}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <fieldset className="space-y-1.5">
              <legend className="mb-1.5 text-sm font-medium">{d.layout}</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {LAYOUTS.map(({ id, Icon }) => {
                  const selected = layout === id;
                  return (
                    <label
                      key={id}
                      className={cn(
                        "flex cursor-pointer gap-3 rounded-xl border p-3 transition-[border-color,background-color,box-shadow] duration-200",
                        "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                        selected
                          ? "border-primary/70 bg-accent shadow-[0_0_18px_-8px_var(--primary)]"
                          : "border-primary/15 hover:border-primary/40 hover:bg-muted/60",
                      )}
                    >
                      <input
                        type="radio"
                        name={groupId}
                        value={id}
                        checked={selected}
                        onChange={() => setLayout(id)}
                        className="sr-only"
                      />
                      <Icon
                        aria-hidden="true"
                        className={cn(
                          "mt-0.5 size-5 shrink-0 transition-colors",
                          selected ? "text-primary" : "text-muted-foreground",
                        )}
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold">{d.layouts[id].title}</span>
                        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                          {d.layouts[id].body}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <div className="grid items-start gap-4 sm:grid-cols-2">
              <Field
                label={d.candidates}
                hint={d.candidatesHint}
                error={candidates === null ? d.candidatesError : undefined}
              >
                {(ids) => (
                  <NumericInput
                    {...ids}
                    value={count}
                    unit={t.units.candidates}
                    invalid={candidates === null}
                    onValueChange={setCount}
                  />
                )}
              </Field>
              <Field label={d.status}>
                {(ids) => (
                  <Select
                    {...ids}
                    value={status}
                    onValueChange={setStatus}
                    options={STATUSES.map((value) => ({ value, label: t.status[value] }))}
                  />
                )}
              </Field>
            </div>

            {error != null && <ErrorNote error={error} />}
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              {t.common.cancel}
            </Button>
            <Button type="submit" loading={busy} disabled={candidates === null}>
              {!busy && <Download className="size-4" aria-hidden="true" />}
              {d.download}
            </Button>
          </DialogFooter>
        </form>
      </AnimatedDialogContent>
    </Dialog>
  );
}

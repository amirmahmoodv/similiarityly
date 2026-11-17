import * as React from "react";
import { motion, useReducedMotion } from "motion/react";
import { AlertCircle } from "lucide-react";
import { SignalTrace } from "@/components/hud/signal-trace";
import { HudSpinner } from "@/components/hud/spinner";
import { AnimatedButton } from "@/components/motion";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { transitions } from "@/lib/motion";
import type { RecordStatus } from "@/lib/types";

// ---- Button ---------------------------------------------------------------

const buttonVariants = {
  primary: "hud-sheen bg-primary font-semibold shadow-[0_0_20px_-6px_var(--primary)] text-primary-foreground hover:shadow-[0_0_32px_-4px_var(--primary)]",
  secondary:
    "border border-primary/25 bg-card hover:border-primary/60 hover:bg-accent hover:text-primary hover:shadow-[0_0_22px_-8px_var(--primary)]",
  ghost: "hover:bg-muted hover:text-primary",
  danger:
    "bg-destructive text-white shadow-[0_0_20px_-6px_var(--destructive)] hover:bg-destructive/90 hover:shadow-[0_0_30px_-4px_var(--destructive)]",
} as const;

type ButtonProps = Omit<React.ComponentProps<typeof AnimatedButton>, "children"> & {
  children?: React.ReactNode;
  variant?: keyof typeof buttonVariants;
  loading?: boolean;
  size?: "md" | "sm";
};

/** The starter's AnimatedButton with product variants and a real loading state. */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading, disabled, className, children, ...props }, ref) => (
    <AnimatedButton
      ref={ref}
      type="button"
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "text-sm ring-offset-background",
        size === "sm" && "px-3 py-1.5",
        buttonVariants[variant],
        className,
      )}
    >
      {loading && <HudSpinner />}
      {children}
    </AnimatedButton>
  ),
);
Button.displayName = "Button";

// ---- Layout ---------------------------------------------------------------

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("hud-panel rounded-2xl border p-5", className)} {...props} />;
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="hud-title hud-glow text-2xl font-bold tracking-tight">{title}</h1>
        <SignalTrace className="w-72 max-w-full" />
        {subtitle && <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  body?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-primary/25 bg-card/40 px-6 py-12 text-center">
      <div className="hud-radar mb-3 rounded-full border border-primary/40 bg-accent p-3 text-primary shadow-[0_0_24px_-6px_var(--primary)]">
        {icon}
      </div>
      <p className="font-semibold">{title}</p>
      {body && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("hud-skeleton rounded-lg", className)} aria-hidden="true" />;
}

/** A skeleton block for a page still loading: the spinner and a label centred on it. */
export function LoadingPanel({ className }: { className?: string }) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "hud-skeleton flex flex-col items-center justify-center gap-3 rounded-lg text-primary",
        className,
      )}
    >
      <HudSpinner className="size-9" />
      <span className="text-sm text-muted-foreground">{t.common.loading}</span>
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t, err } = useI18n();
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/40 bg-dup-soft px-4 py-3 text-sm"
    >
      <AlertCircle className="size-4 shrink-0 text-destructive" aria-hidden="true" />
      <span className="flex-1">{err(error)}</span>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {t.common.retry}
        </Button>
      )}
    </div>
  );
}

// ---- Form controls --------------------------------------------------------

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  /** Receives the id/aria wiring for the control. */
  children: (ids: { id: string; "aria-describedby"?: string }) => React.ReactNode;
  className?: string;
}) {
  const id = React.useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children({ id, "aria-describedby": note ? noteId : undefined })}
      {note && (
        <p
          id={noteId}
          role={error ? "alert" : undefined}
          className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}
        >
          {note}
        </p>
      )}
    </div>
  );
}

const controlClass =
  "w-full rounded-lg border bg-background/60 px-3 py-2 text-sm outline-none transition-[box-shadow,border-color] duration-200 hover:border-primary/40 focus-visible:border-primary/70 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:shadow-[0_0_18px_-6px_var(--primary)] disabled:opacity-60";

export const TextInput = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input ref={ref} type="text" {...props} className={cn(controlClass, className)} />
));
TextInput.displayName = "TextInput";

export const TextArea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} {...props} className={cn(controlClass, "leading-7", className)} />
));
TextArea.displayName = "TextArea";

export function Select<T extends string>({
  value,
  onValueChange,
  options,
  className,
  ...props
}: Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange"> & {
  value: T;
  onValueChange: (value: T) => void;
  options: { value: T; label: string; disabled?: boolean }[];
}) {
  return (
    <select
      {...props}
      value={value}
      onChange={(e) => onValueChange(e.target.value as T)}
      className={cn(controlClass, "pe-8", className)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Switch({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-1.5 text-sm">
      <span>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          "flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors",
          "outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          checked ? "justify-end bg-primary" : "justify-start bg-border",
        )}
      >
        <motion.span
          layout
          transition={reduceMotion ? { duration: 0.01 } : transitions.tactile}
          className="size-5 rounded-full bg-white shadow-sm"
        />
      </button>
    </label>
  );
}

// ---- Similarity display ---------------------------------------------------

// `text` sets currentColor on the bar so its glow matches the status colour.
const statusStyles: Record<RecordStatus, { badge: string; bar: string; text: string }> = {
  duplicate: { badge: "border border-dup/40 bg-dup-soft text-dup", bar: "bg-dup", text: "text-dup" },
  similar: { badge: "border border-sim/40 bg-sim-soft text-sim", bar: "bg-sim", text: "text-sim" },
  unique: { badge: "border border-uniq/40 bg-uniq-soft text-uniq", bar: "bg-uniq", text: "text-uniq" },
};

export function StatusBadge({ status }: { status: RecordStatus }) {
  const { t } = useI18n();
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        statusStyles[status].badge,
      )}
    >
      {t.status[status]}
    </span>
  );
}

/** A 0..1 score as a labelled percentage with a proportional bar. */
export function ScoreMeter({ score, status }: { score: number; status: RecordStatus }) {
  const { pct } = useI18n();
  return (
    <div className="flex min-w-28 items-center gap-2">
      <span className="nums w-14 shrink-0 text-sm font-semibold">{pct(score)}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div
          className={cn("hud-fill h-full rounded-full", statusStyles[status].bar, statusStyles[status].text)}
          style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }}
        />
      </div>
    </div>
  );
}

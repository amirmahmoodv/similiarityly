import { cn } from "@/lib/cn";

/** Loading mark: two arcs turning against each other around a core. */
export function HudSpinner({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("hud-spinner size-4 shrink-0", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle className="hud-spinner-a" cx="12" cy="12" r="9.5" strokeDasharray="20 39.7" />
      <circle className="hud-spinner-b" cx="12" cy="12" r="5.5" strokeDasharray="10 24.6" opacity=".7" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

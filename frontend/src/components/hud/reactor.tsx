import { cn } from "@/lib/cn";

/**
 * connecting: no answer from the server yet · online: idle and reachable ·
 * active: jobs are queued or running · offline: the server did not answer.
 */
export type ReactorState = "connecting" | "online" | "active" | "offline";

/**
 * The product mark (two overlapping sets) inside a ring assembly. Rotation
 * speed and colour are driven by `state` in hud.css, so it only looks busy
 * when the system really is.
 */
export function Reactor({ state, className }: { state: ReactorState; className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      data-state={state}
      className={cn("reactor shrink-0", className)}
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
    >
      <circle className="reactor-outer" cx="32" cy="32" r="30" strokeWidth="1" strokeDasharray="2 5" opacity=".55" />
      <circle
        className="reactor-arcs"
        cx="32"
        cy="32"
        r="25"
        strokeWidth="2.5"
        strokeDasharray="38 14.36"
        strokeLinecap="round"
      />
      <circle cx="32" cy="32" r="19.5" strokeWidth="1" opacity=".35" />
      <g className="reactor-core" strokeWidth="2.6">
        <circle cx="27.5" cy="32" r="8.5" />
        <circle cx="36.5" cy="32" r="8.5" opacity=".7" />
        <path
          d="M32 24.8a8.5 8.5 0 0 1 0 14.4a8.5 8.5 0 0 1 0-14.4Z"
          fill="currentColor"
          fillOpacity=".35"
          stroke="none"
        />
      </g>
    </svg>
  );
}

import * as React from "react";
import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import type { ReactorState } from "./reactor";

/**
 * Pointer-driven effects, attached once for the whole app:
 *  - panels and buttons receive the pointer position (their glow follows it);
 *  - `.hud-tilt` cards lean toward the pointer;
 *  - every press leaves a short expanding ring where it landed.
 */
export function usePointerEffects() {
  React.useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

    const track = (el: HTMLElement | null, event: PointerEvent) => {
      if (!el) return;
      const rect = el.getBoundingClientRect();
      el.style.setProperty("--hud-x", `${event.clientX - rect.left}px`);
      el.style.setProperty("--hud-y", `${event.clientY - rect.top}px`);
    };
    // The one card currently tilted toward the pointer.
    let tilted: HTMLElement | null = null;
    const level = () => {
      tilted?.style.removeProperty("--hud-rx");
      tilted?.style.removeProperty("--hud-ry");
      tilted = null;
    };
    const tilt = (el: HTMLElement | null, event: PointerEvent) => {
      if (el !== tilted) level();
      if (!el || reduce.matches) return;
      const rect = el.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      el.style.setProperty("--hud-rx", `${(-y * 7).toFixed(2)}deg`);
      el.style.setProperty("--hud-ry", `${(x * 9).toFixed(2)}deg`);
      tilted = el;
    };

    const onMove = (event: PointerEvent) => {
      if (event.pointerType === "touch" || !(event.target instanceof Element)) return;
      track(event.target.closest<HTMLElement>(".hud-btn"), event);
      track(event.target.closest<HTMLElement>(".hud-panel"), event);
      tilt(event.target.closest<HTMLElement>(".hud-tilt"), event);
    };

    const onDown = (event: PointerEvent) => {
      if (reduce.matches || event.button !== 0) return;
      const ping = document.createElement("span");
      ping.className = "hud-ping";
      ping.setAttribute("aria-hidden", "true");
      ping.style.left = `${event.clientX}px`;
      ping.style.top = `${event.clientY}px`;
      ping.append(document.createElement("i"), document.createElement("i"));
      document.body.appendChild(ping);
      window.setTimeout(() => ping.remove(), 900);
    };

    document.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerdown", onDown, { passive: true });
    document.documentElement.addEventListener("pointerleave", level);
    return () => {
      document.documentElement.removeEventListener("pointerleave", level);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerdown", onDown);
    };
  }, []);
}

/** Ripple that spreads inside a control from the point it was pressed. */
export function spawnRipple(event: React.PointerEvent<HTMLElement>) {
  const el = event.currentTarget;
  const rect = el.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 2.2;
  const ripple = document.createElement("span");
  ripple.className = "hud-ripple";
  ripple.setAttribute("aria-hidden", "true");
  ripple.style.width = ripple.style.height = `${size}px`;
  ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
  ripple.style.top = `${event.clientY - rect.top - size / 2}px`;
  el.appendChild(ripple);
  window.setTimeout(() => ripple.remove(), 700);
}

/**
 * Top-edge bar shown only while a first load or a save is really in flight
 * (background polling does not trigger it).
 */
export function FetchBar() {
  const fetching = useIsFetching({ predicate: (query) => query.state.status === "pending" });
  const mutating = useIsMutating();
  return (
    <div aria-hidden="true" className={cn("hud-fetchbar", fetching + mutating > 0 && "is-on")}>
      <span />
    </div>
  );
}

/** A smooth repeating wave; `period` must divide 1440 so the loop is seamless. */
function wavePath(period: number, amplitude: number, mid: number): string {
  let d = `M0 ${mid}`;
  for (let x = 0; x < 2880; x += period) {
    d += ` Q${x + period / 4} ${mid - amplitude} ${x + period / 2} ${mid} T${x + period} ${mid}`;
  }
  return d;
}

const WAVES = [
  { period: 720, amplitude: 46, mid: 110, seconds: 22, opacity: 0.5, width: 1.6, fill: true },
  { period: 480, amplitude: 28, mid: 125, seconds: 14, opacity: 0.38, width: 1.2, fill: false },
  { period: 360, amplitude: 16, mid: 140, seconds: 9, opacity: 0.3, width: 1, fill: false },
] as const;

/**
 * Signal waves flowing across the bottom of every screen. They follow the same
 * state as the reactor: faster while jobs run, red and frozen when offline.
 */
export function WaveField({ state }: { state: ReactorState }) {
  return (
    <div aria-hidden="true" data-state={state} className="hud-waves">
      {WAVES.map((wave) => {
        const line = wavePath(wave.period, wave.amplitude, wave.mid);
        return (
          <svg
            key={wave.period}
            viewBox="0 0 2880 200"
            preserveAspectRatio="none"
            style={{ "--d": `${wave.seconds}s`, opacity: wave.opacity } as React.CSSProperties}
          >
            {wave.fill && (
              <path d={`${line} V200 H0 Z`} fill="currentColor" fillOpacity="0.09" stroke="none" />
            )}
            <path
              d={line}
              fill="none"
              stroke="currentColor"
              strokeWidth={wave.width}
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        );
      })}
    </div>
  );
}

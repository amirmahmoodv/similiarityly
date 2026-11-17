import * as React from "react";
import { cn } from "@/lib/cn";

const WIDTH = 288;
const HEIGHT = 34;
/** The flat line sits low, leaving room above it for the tall spike. */
const BASE = 24;
/** Pixels per second a beat drifts toward the end edge. */
const SPEED = 40;
/** Seconds of quiet between two beats appearing: short runs and long ones. */
const MIN_WAIT = 0.25;
const MAX_WAIT = 3.4;
/** Seconds a beat takes to rise out of the line, and to sink back into it. */
const RISE = 0.25;
const SINK = 0.45;
/** Beats keep at least this much flat line between them, in pixels. */
const CLEARANCE = 10;

/**
 * One heartbeat on the line: `half` is half its width, `amp` its spike height
 * in pixels. The rest shapes it, as fractions of `amp` (`lean` of `half`).
 */
type Beat = {
  x: number;
  half: number;
  amp: number;
  p: number;
  q: number;
  s: number;
  t: number;
  lean: number;
  age: number;
  life: number;
};

const between = (min: number, max: number) => min + Math.random() * (max - min);

/** A beat somewhere along the line, clear of the others; null if it is crowded. */
function newBeat(others: Beat[]): Beat | null {
  const half = between(13, 30);
  for (let attempt = 0; attempt < 6; attempt++) {
    // Not in the last stretch, where the line has already faded out.
    const x = between(half, WIDTH * 0.8);
    if (others.every((o) => Math.abs(o.x - x) > o.half + half + CLEARANCE)) {
      return {
        x,
        half,
        // From a modest blip up to the full height of the strip.
        amp: between(10, 23),
        p: between(0.05, 0.22),
        q: between(0.04, 0.22),
        s: between(0.1, 0.42),
        t: between(0.1, 0.38),
        lean: between(-0.07, 0.07),
        age: 0,
        life: between(0.8, 2.4),
      };
    }
  }
  return null;
}

/** 0..1: how far the beat stands out of the line at this point of its life. */
function height(b: Beat): number {
  const t = Math.max(0, Math.min(1, b.age / RISE, (b.life - b.age) / SINK));
  return t * t * (3 - 2 * t);
}

const n = (v: number) => v.toFixed(1);

/** A smooth hump from x0 to x1, `h` pixels above the line. */
function hump(x0: number, x1: number, h: number): string {
  const mid = (x0 + x1) / 2;
  const lean = (x1 - x0) * 0.22;
  const top = n(BASE - h);
  return (
    `L${n(x0)} ${BASE}` +
    `C${n(x0 + lean)} ${BASE} ${n(mid - lean)} ${top} ${n(mid)} ${top}` +
    `C${n(mid + lean)} ${top} ${n(x1 - lean)} ${BASE} ${n(x1)} ${BASE}`
  );
}

/**
 * The line with each beat drawn where it currently is, as a heart monitor
 * shows one: a small wave, a dip, the tall spike, a deeper dip, then a wider
 * wave (P, Q, R, S, T).
 */
function tracePath(beats: Beat[]): string {
  let d = `M-1 ${BASE}`;
  for (const b of [...beats].sort((a, z) => a.x - z.x)) {
    const amp = b.amp * height(b);
    const at = (u: number, y: number) => `L${n(b.x + u * b.half)} ${n(BASE - y * amp)}`;
    d +=
      hump(b.x - b.half, b.x - 0.55 * b.half, b.p * amp) +
      at(-0.28, 0) +
      at(-0.2, -b.q) +
      at(-0.08 + b.lean, 1) +
      at(0.05, -b.s) +
      at(0.15, 0) +
      hump(b.x + 0.38 * b.half, b.x + b.half, b.t * amp);
  }
  return `${d}L${WIDTH + 1} ${BASE}`;
}

/**
 * The rule under a page title: a flat line on which a heartbeat rises every so
 * often, at a random place, size and moment, drifts toward the end edge for a
 * second or two and sinks back into the line. Decorative; it keeps running
 * under reduced motion (see hud.css), at half speed.
 */
export function SignalTrace({ className }: { className?: string }) {
  const path = React.useRef<SVGPathElement>(null);

  React.useEffect(() => {
    const rate = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0.5 : 1;
    let beats: Beat[] = [];
    let wait = between(0.2, 0.9);
    let last = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      // A background tab stops the frames; do not jump ahead on return.
      const dt = rate * Math.min(0.1, (now - last) / 1000);
      last = now;
      for (const b of beats) {
        b.x += SPEED * dt;
        b.age += dt;
      }
      beats = beats.filter((b) => b.age < b.life && b.x - b.half < WIDTH);
      wait -= dt;
      if (wait <= 0) {
        const next = newBeat(beats);
        if (next) beats.push(next);
        wait = between(MIN_WAIT, MAX_WAIT);
      }
      path.current?.setAttribute("d", tracePath(beats));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div
      aria-hidden="true"
      style={{ height: HEIGHT }}
      className={cn("hud-rule hud-signal text-primary", className)}
    >
      {/* Drawn start-to-end; mirrored so it also runs from the start edge in RTL. */}
      <svg
        width={WIDTH}
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        fill="none"
        className="rtl:-scale-x-100"
      >
        <path
          ref={path}
          d={`M-1 ${BASE}L${WIDTH + 1} ${BASE}`}
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

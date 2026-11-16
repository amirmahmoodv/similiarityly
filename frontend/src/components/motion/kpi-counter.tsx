"use client";

import * as React from "react";
import { motion, useReducedMotion } from "motion/react";

type Props = {
  value: number;
  format?: (value: number) => string;
  durationMs?: number;
  className?: string;
  /** Optional accessible label for the value. */
  label?: string;
};

export function KpiCounter({
  value,
  format = (n) => Math.round(n).toLocaleString(),
  durationMs = 700,
  className,
  label,
}: Props) {
  const reduceMotion = useReducedMotion();
  // Starts at zero so the figure counts up once when its tile first appears.
  const [displayValue, setDisplayValue] = React.useState(reduceMotion ? value : 0);
  const previous = React.useRef(reduceMotion ? value : 0);

  React.useEffect(() => {
    if (reduceMotion || !Number.isFinite(value)) {
      setDisplayValue(value);
      previous.current = value;
      return;
    }

    const startValue = previous.current;
    const delta = value - startValue;
    const startTime = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      const progress = Math.min(1, (now - startTime) / durationMs);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayValue(startValue + delta * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
      else previous.current = value;
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, durationMs, reduceMotion]);

  return (
    <motion.span
      className={className}
      aria-label={label}
      aria-live="off"
      initial={false}
      animate={reduceMotion ? undefined : { opacity: [0.8, 1] }}
      transition={{ duration: 0.2 }}
    >
      {format(displayValue)}
    </motion.span>
  );
}

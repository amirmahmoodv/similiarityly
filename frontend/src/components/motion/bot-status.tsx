"use client";

import { motion, useReducedMotion } from "motion/react";

export type BotState = "idle" | "listening" | "thinking" | "streaming" | "tool" | "success" | "error";

const stateLabels: Record<BotState, string> = {
  idle: "Ready",
  listening: "Listening",
  thinking: "Thinking",
  streaming: "Responding",
  tool: "Working with a tool",
  success: "Completed",
  error: "Something went wrong",
};

type Props = {
  state: BotState;
  label?: string;
  className?: string;
};

export function BotStatus({ state, label, className }: Props) {
  const reduceMotion = useReducedMotion();
  const active = state === "listening" || state === "thinking" || state === "streaming" || state === "tool";

  return (
    <div className={["inline-flex items-center gap-2 text-sm", className].filter(Boolean).join(" ")} role="status" aria-live="polite">
      <span className="relative flex size-2.5 shrink-0">
        {active && !reduceMotion && (
          <motion.span
            className="absolute inline-flex size-full rounded-full bg-current opacity-40"
            animate={{ scale: [1, 1.8], opacity: [0.4, 0] }}
            transition={{ duration: 1.2, repeat: Infinity, ease: "easeOut" }}
          />
        )}
        <span className="relative inline-flex size-2.5 rounded-full bg-current" />
      </span>
      <span>{label ?? stateLabels[state]}</span>
      {(state === "thinking" || state === "tool") && !reduceMotion && (
        <span aria-hidden="true" className="inline-flex gap-0.5">
          {[0, 1, 2].map((n) => (
            <motion.span
              key={n}
              className="size-1 rounded-full bg-current"
              animate={{ opacity: [0.35, 1, 0.35], y: [0, -2, 0] }}
              transition={{ duration: 0.8, repeat: Infinity, delay: n * 0.12 }}
            />
          ))}
        </span>
      )}
    </div>
  );
}

"use client";

import * as React from "react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";

export type AnimatedTabItem = {
  id: string;
  label: React.ReactNode;
  disabled?: boolean;
};

type Props = {
  items: AnimatedTabItem[];
  value: string;
  onValueChange: (value: string) => void;
  label?: string;
  className?: string;
};

export function AnimatedTabs({ items, value, onValueChange, label = "Sections", className }: Props) {
  const reduceMotion = useReducedMotion();

  return (
    <LayoutGroup>
      <div role="tablist" aria-label={label} className={["inline-flex max-w-full gap-1 overflow-x-auto rounded-xl border border-primary/15 bg-muted/60 p-1", className].filter(Boolean).join(" ")}>
        {items.map((item) => {
          const selected = item.id === value;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={selected}
              disabled={item.disabled}
              onClick={() => onValueChange(item.id)}
              className={[
                "relative isolate shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                selected ? "text-primary" : "text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              {selected && (
                <motion.span
                  layoutId="animated-tabs-indicator"
                  className="absolute inset-0 -z-10 rounded-lg border border-primary/30 bg-accent shadow-[inset_0_-2px_0_var(--primary),0_0_18px_-8px_var(--primary)]"
                  transition={reduceMotion ? { duration: 0.01 } : { type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}

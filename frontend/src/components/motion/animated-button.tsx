"use client";

import * as React from "react";
import { motion, useReducedMotion, type HTMLMotionProps } from "motion/react";
import { spawnRipple } from "@/components/hud/effects";
import { transitions } from "@/lib/motion";

// Adapted from the starter: motion.button rejects React's native drag handler types.
type Props = Omit<HTMLMotionProps<"button">, "ref"> & {
  /** Set false for controls whose scale change would be distracting. */
  tactile?: boolean;
};

/**
 * Hover: lifts, a glow follows the pointer and a sheen crosses it (hud.css).
 * Press: sinks, and a ripple spreads from the point of contact.
 */
export const AnimatedButton = React.forwardRef<HTMLButtonElement, Props>(
  ({ tactile = true, className, disabled, children, onPointerDown, ...props }, ref) => {
    const reduceMotion = useReducedMotion();

    return (
      <motion.button
        ref={ref}
        {...props}
        disabled={disabled}
        onPointerDown={(event) => {
          if (!reduceMotion && event.button === 0) spawnRipple(event);
          onPointerDown?.(event);
        }}
        whileHover={!disabled && !reduceMotion ? { y: -2, scale: 1.03 } : undefined}
        whileTap={!disabled && tactile && !reduceMotion ? { y: 0, scale: 0.95 } : undefined}
        transition={transitions.tactile}
        className={[
          "hud-btn inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2",
          "font-medium transition-[background-color,border-color,color,box-shadow] duration-200",
          "focus-visible:outline-none focus-visible:ring-2",
          "focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none",
          "disabled:opacity-50",
          className,
        ].filter(Boolean).join(" ")}
      >
        {children}
      </motion.button>
    );
  },
);

AnimatedButton.displayName = "AnimatedButton";

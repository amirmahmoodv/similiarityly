"use client";

import * as React from "react";
import { motion, useReducedMotion } from "motion/react";
import { motionTokens } from "@/lib/motion";

type Props = {
  children: React.ReactNode;
  /** Pass pathname or a stable route/view identifier. */
  transitionKey: string;
  className?: string;
};

/** Route change: a scan line crosses the top edge while the new view rises in. */
export function PageTransition({ children, transitionKey, className }: Props) {
  const reduceMotion = useReducedMotion();
  const ease = motionTokens.ease.standard;

  return (
    <div className={className}>
      {!reduceMotion && (
        <motion.div
          key={`${transitionKey}:scan`}
          aria-hidden="true"
          className="pointer-events-none -mb-px h-px bg-linear-to-r from-transparent via-primary to-transparent"
          initial={{ scaleX: 0, opacity: 1 }}
          animate={{ scaleX: 1, opacity: 0 }}
          transition={{ scaleX: { duration: 0.45, ease }, opacity: { duration: 0.3, delay: 0.35 } }}
        />
      )}
      {!reduceMotion && (
        // A soft band of light travels down the viewport once per route change.
        <motion.div
          key={`${transitionKey}:sweep`}
          aria-hidden="true"
          className="pointer-events-none fixed inset-x-0 top-0 z-20 h-32 bg-linear-to-b from-transparent via-primary/12 to-transparent"
          initial={{ y: "-100%", opacity: 1 }}
          animate={{ y: "100vh", opacity: 0 }}
          transition={{ y: { duration: 0.9, ease }, opacity: { duration: 0.3, delay: 0.6 } }}
        />
      )}
      <motion.div
        key={transitionKey}
        className="hud-page"
        initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.992 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={reduceMotion ? { duration: 0.01 } : { duration: motionTokens.duration.panel, ease }}
      >
        {children}
      </motion.div>
    </div>
  );
}

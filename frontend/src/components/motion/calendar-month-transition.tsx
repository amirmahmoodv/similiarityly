"use client";

import * as React from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

type Props = {
  /** Change this key when the visible month or calendar view changes. */
  viewKey: string | number;
  children: React.ReactNode;
  className?: string;
  direction?: 1 | -1;
};

export function CalendarMonthTransition({
  viewKey,
  children,
  className,
  direction = 1,
}: Props) {
  const reduceMotion = useReducedMotion();

  return (
    <div className={className}>
      <AnimatePresence mode="wait" initial={false} custom={direction}>
        <motion.div
          key={viewKey}
          custom={direction}
          initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: direction * 12 }}
          animate={{ opacity: 1, x: 0 }}
          exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: direction * -12 }}
          transition={reduceMotion ? { duration: 0.01 } : { duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

"use client";

import * as React from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

type Props = {
  children: React.ReactNode;
  className?: string;
  /** Use only for reasonably sized lists; avoid animating thousands of rows. */
  animateLayout?: boolean;
};

export function AnimatedList({ children, className, animateLayout = true }: Props) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      className={className}
      layout={animateLayout && !reduceMotion}
      transition={reduceMotion ? { duration: 0.01 } : { layout: { type: "spring", stiffness: 360, damping: 32 } as never }}
    >
      <AnimatePresence initial={false}>
        {React.Children.map(children, (child) => {
          if (!React.isValidElement<{ key?: React.Key }>(child)) return child;
          return (
            <motion.div
              key={child.key ?? undefined}
              layout={animateLayout && !reduceMotion}
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: reduceMotion ? 0 : -4 }}
              transition={reduceMotion ? { duration: 0.01 } : { duration: 0.18 }}
            >
              {child}
            </motion.div>
          );
        })}
      </AnimatePresence>
    </motion.div>
  );
}

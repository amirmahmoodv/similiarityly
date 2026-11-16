"use client";

import * as React from "react";
import { motion, useReducedMotion } from "motion/react";
import { DialogContent } from "@/components/ui/dialog";
import { popoverVariants } from "@/lib/motion";

/**
 * Use as the content primitive inside the existing shadcn Dialog.
 * DialogContent retains Radix focus management and accessibility behavior.
 */
export const AnimatedDialogContent = React.forwardRef<
  React.ElementRef<typeof DialogContent>,
  React.ComponentPropsWithoutRef<typeof DialogContent>
>(({ children, ...props }, ref) => {
  const reduceMotion = useReducedMotion();

  return (
    <DialogContent ref={ref} {...props}>
      <motion.div
        variants={popoverVariants}
        initial={reduceMotion ? false : "hidden"}
        animate="visible"
        exit="exit"
        transition={reduceMotion ? { duration: 0.01 } : undefined}
      >
        {children}
      </motion.div>
    </DialogContent>
  );
});

AnimatedDialogContent.displayName = "AnimatedDialogContent";

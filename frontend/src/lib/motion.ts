import type { Transition, Variants } from "motion/react";

export const motionTokens = {
  duration: {
    fast: 0.15,
    standard: 0.22,
    panel: 0.3,
  },
  ease: {
    standard: [0.22, 1, 0.36, 1] as const,
    exit: [0.4, 0, 1, 1] as const,
  },
  spring: {
    tactile: { type: "spring", stiffness: 420, damping: 28, mass: 0.7 },
    gentle: { type: "spring", stiffness: 260, damping: 26, mass: 0.85 },
  },
} as const;

export const transitions = {
  fast: {
    duration: motionTokens.duration.fast,
    ease: motionTokens.ease.standard,
  },
  standard: {
    duration: motionTokens.duration.standard,
    ease: motionTokens.ease.standard,
  },
  panel: {
    duration: motionTokens.duration.panel,
    ease: motionTokens.ease.standard,
  },
  tactile: motionTokens.spring.tactile,
} satisfies Record<string, Transition>;

export const fadeUpVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: transitions.standard,
  },
  exit: {
    opacity: 0,
    y: 4,
    transition: { duration: motionTokens.duration.fast, ease: motionTokens.ease.exit },
  },
};

export const popoverVariants: Variants = {
  hidden: { opacity: 0, scale: 0.97, y: -4 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: transitions.standard,
  },
  exit: {
    opacity: 0,
    scale: 0.98,
    y: -2,
    transition: { duration: motionTokens.duration.fast, ease: motionTokens.ease.exit },
  },
};

export const reducedMotionFade = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.01 },
} as const;

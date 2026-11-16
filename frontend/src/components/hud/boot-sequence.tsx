import * as React from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { motionTokens } from "@/lib/motion";
import { Reactor } from "./reactor";

const SEEN_KEY = "similarityly.booted";

function alreadySeen(): boolean {
  try {
    return sessionStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Short power-on reveal, once per browser session. Purely decorative: it shows
 * no progress, never intercepts input, and is skipped under reduced motion.
 */
export function BootSequence({ name }: { name: string }) {
  const reduceMotion = useReducedMotion();
  const [show, setShow] = React.useState(() => !alreadySeen());

  React.useEffect(() => {
    if (!show) return;
    try {
      sessionStorage.setItem(SEEN_KEY, "1");
    } catch {
      /* storage unavailable: the reveal simply plays again next load */
    }
    const id = window.setTimeout(() => setShow(false), 850);
    return () => window.clearTimeout(id);
  }, [show]);

  if (reduceMotion) return null;

  const ease = motionTokens.ease.standard;
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-[60] grid place-items-center bg-background"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4, ease: motionTokens.ease.exit }}
        >
          <motion.div
            className="flex flex-col items-center gap-5"
            exit={{ scale: 1.12, opacity: 0 }}
            transition={{ duration: 0.4, ease }}
          >
            <motion.div
              initial={{ scale: 0.55, opacity: 0, rotate: -90 }}
              animate={{ scale: 1, opacity: 1, rotate: 0 }}
              transition={{ duration: 0.6, ease }}
            >
              <Reactor state="online" className="size-28" />
            </motion.div>
            <motion.div
              className="hud-glow text-xl font-bold text-primary"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: 0.2, ease }}
            >
              {name}
            </motion.div>
            <motion.div
              className="h-px w-56 bg-linear-to-r from-transparent via-primary to-transparent"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.55, delay: 0.15, ease }}
            />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

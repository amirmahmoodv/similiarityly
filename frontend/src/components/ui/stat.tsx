import * as React from "react";
import { KpiCounter } from "@/components/motion";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { Card } from "./primitives";

type Props = {
  label: string;
  value: number;
  /** Translated unit; the magnitude word (میلیون/میلیارد) is prepended when rescaled. */
  unit: string;
  icon?: React.ReactNode;
  tone?: "default" | "dup" | "sim" | "uniq";
};

const tones = {
  default: "text-primary",
  dup: "text-dup",
  sim: "text-sim",
  uniq: "text-uniq",
};

/**
 * KPI tile. Large values are rescaled (never clipped) with the magnitude moved
 * to the unit line, and the full value stays available in the tooltip. If the
 * text still overflows its box the font steps down instead of truncating.
 */
export function Stat({ label, value, unit, icon, tone = "default" }: Props) {
  const { kpi, n, t } = useI18n();
  const { magnitude, full } = kpi(value);
  const divisor = magnitude === "billion" ? 1e9 : magnitude === "million" ? 1e6 : 1;
  const unitLine = magnitude === "none" ? unit : `${t.units[magnitude]} ${unit}`;

  const box = React.useRef<HTMLDivElement>(null);
  const [step, setStep] = React.useState(0);
  React.useLayoutEffect(() => {
    const el = box.current;
    if (el && el.scrollWidth > el.clientWidth && step < 2) setStep(step + 1);
  }, [full, step]);

  return (
    <Card className="hud-tilt min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="hud-label">{label}</span>
        {icon && (
          <span className="hud-chip grid size-8 shrink-0 place-items-center rounded-full border border-primary/35 bg-accent/60 text-primary shadow-[0_0_14px_-5px_var(--primary)]">
            {icon}
          </span>
        )}
      </div>
      <div
        ref={box}
        title={`${full} ${unit}`}
        className={cn(
          "hud-glow nums mt-2 whitespace-nowrap font-bold",
          ["text-3xl", "text-2xl", "text-xl"][step],
          tones[tone],
        )}
      >
        <KpiCounter
          value={value}
          format={(v) => n(v / divisor, magnitude === "none" ? 0 : 1)}
        />
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{unitLine}</div>
    </Card>
  );
}

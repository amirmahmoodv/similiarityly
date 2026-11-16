import * as React from "react";
import { ApiError } from "@/lib/api";
import {
  formatDateTime,
  formatKpi,
  formatNumber,
  formatRatioAsPercent,
  type Locale,
} from "@/lib/format";
import { en } from "./en";
import { fa, type Dictionary } from "./fa";

const dictionaries: Record<Locale, Dictionary> = { fa, en };
const STORAGE_KEY = "similarityly.locale";

type I18n = {
  locale: Locale;
  dir: "rtl" | "ltr";
  t: Dictionary;
  setLocale: (locale: Locale) => void;
  /** Grouped, localized number. */
  n: (value: number, maxFractionDigits?: number) => string;
  /** 0..1 ratio → "۹۲٫۵٪" (number and translated unit together). */
  pct: (ratio: number) => string;
  kpi: (value: number) => ReturnType<typeof formatKpi>;
  date: (iso: string) => string;
  /** Translate an API error code, falling back to a generic message. */
  err: (error: unknown) => string;
};

const Context = React.createContext<I18n | null>(null);

function initialLocale(): Locale {
  try {
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "fa";
  } catch {
    return "fa";
  }
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = React.useState<Locale>(initialLocale);
  const dir = locale === "fa" ? "rtl" : "ltr";

  React.useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
    document.title = locale === "fa" ? "همسان‌یاب | Similarityly" : "Similarityly";
  }, [locale, dir]);

  const value = React.useMemo<I18n>(() => {
    const t = dictionaries[locale];
    return {
      locale,
      dir,
      t,
      setLocale: (next) => {
        try {
          localStorage.setItem(STORAGE_KEY, next);
        } catch {
          /* storage unavailable: the choice just won't persist */
        }
        setLocaleState(next);
      },
      n: (value, digits) => formatNumber(value, locale, digits),
      pct: (ratio) => `${formatRatioAsPercent(ratio, locale)}${t.units.percent}`,
      kpi: (value) => formatKpi(value, locale),
      date: (iso) => formatDateTime(iso, locale),
      err: (error) => {
        const code = error instanceof ApiError ? error.code : "unknown_error";
        const known = t.errors as Record<string, string>;
        return known[code] ?? known.unknown_error;
      },
    };
  }, [locale, dir]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const ctx = React.useContext(Context);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}

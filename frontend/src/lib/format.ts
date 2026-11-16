/**
 * The one place numbers become text. No component renders a bare number.
 *
 * fa: digits ۰–۹, group ٬ (U+066C), decimal ٫ (U+066B)
 * en: digits 0–9, group ,          decimal .
 */

export type Locale = "fa" | "en";

const SEPARATORS: Record<Locale, { group: string; decimal: string }> = {
  fa: { group: "٬", decimal: "٫" },
  en: { group: ",", decimal: "." },
};

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";

export function toAsciiDigits(input: string): string {
  return input.replace(/[۰-۹٠-٩]/g, (ch) => {
    const fa = FA_DIGITS.indexOf(ch);
    return String(fa >= 0 ? fa : AR_DIGITS.indexOf(ch));
  });
}

export function localizeDigits(input: string, locale: Locale): string {
  return locale === "fa" ? input.replace(/\d/g, (d) => FA_DIGITS[Number(d)]) : input;
}

/**
 * Display form of a raw ASCII numeric string ("1234.5" → "۱٬۲۳۴٫۵").
 * Pure string work, so partial input ("12.") and long values survive intact.
 */
export function formatRaw(raw: string, locale: Locale): string {
  if (raw === "") return "";
  const { group, decimal } = SEPARATORS[locale];
  const negative = raw.startsWith("-");
  const [int, frac] = (negative ? raw.slice(1) : raw).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, group);
  const body = frac === undefined ? grouped : `${grouped}${decimal}${frac}`;
  return localizeDigits(`${negative ? "-" : ""}${body}`, locale);
}

export function formatNumber(value: number, locale: Locale, maxFractionDigits = 0): string {
  if (!Number.isFinite(value)) return "—";
  const fixed = value.toFixed(maxFractionDigits);
  const trimmed = fixed.includes(".") ? fixed.replace(/\.?0+$/, "") : fixed;
  return formatRaw(trimmed === "-0" ? "0" : trimmed, locale);
}

/** A 0..1 similarity ratio as the number part of a percentage (unit rendered separately). */
export function formatRatioAsPercent(ratio: number, locale: Locale, maxFractionDigits = 1): string {
  return formatNumber(ratio * 100, locale, maxFractionDigits);
}

export type Magnitude = "none" | "million" | "billion";

/**
 * KPI rescaling: never truncate, move the magnitude into the caption instead.
 * ≥1e9 → ÷1e9 "billion"; ≥1e7 → ÷1e6 "million"; below that grouped in full.
 */
export function formatKpi(
  value: number,
  locale: Locale,
): { text: string; magnitude: Magnitude; full: string } {
  const full = formatNumber(value, locale);
  const abs = Math.abs(value);
  if (abs >= 1e9) return { text: formatNumber(value / 1e9, locale, 1), magnitude: "billion", full };
  if (abs >= 1e7) return { text: formatNumber(value / 1e6, locale, 1), magnitude: "million", full };
  return { text: full, magnitude: "none", full };
}

/**
 * Parse whatever the user typed or pasted into a raw ASCII numeric string.
 * Accepts Persian/Arabic-Indic digits, either group separator, either decimal
 * mark (and "/", the decimal key on Persian keyboards). Returns null when the
 * text is not a (possibly partial) number, so the caller can reject the keystroke.
 */
export function parseNumericInput(text: string, allowDecimal = true): string | null {
  let s = toAsciiDigits(text)
    .replace(/[\s,٬‎‏]/g, "")
    .replace(/[٫/]/g, ".");
  if (!/^\d*(\.\d*)?$/.test(s)) return null;
  if (!allowDecimal && s.includes(".")) return null;
  if (s.startsWith(".")) s = `0${s}`;
  s = s.replace(/^0+(?=\d)/, "");
  return s;
}

/** Raw string → number at the API edge. Empty or partial input is NaN. */
export function rawToNumber(raw: string): number {
  return raw === "" || raw.endsWith(".") ? Number.NaN : Number(raw);
}

export function formatDateTime(iso: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "fa" ? "fa-IR" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

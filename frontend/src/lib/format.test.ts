import { describe, expect, it } from "vitest";
import {
  formatKpi,
  formatNumber,
  formatRatioAsPercent,
  formatRaw,
  parseNumericInput,
  rawToNumber,
  toAsciiDigits,
} from "./format";
import { digitsBefore, caretAfterDigits } from "./caret";
import { configToDraft, draftToConfig } from "./units";
import type { RepoConfig } from "./types";

describe("formatNumber", () => {
  it("groups and localizes for both locales", () => {
    expect(formatNumber(1234567, "en")).toBe("1,234,567");
    expect(formatNumber(1234567, "fa")).toBe("۱٬۲۳۴٬۵۶۷");
    expect(formatNumber(1234.5, "fa", 1)).toBe("۱٬۲۳۴٫۵");
    expect(formatNumber(0, "fa")).toBe("۰");
  });

  it("drops a trailing .0 and caps decimals", () => {
    expect(formatNumber(92, "en", 1)).toBe("92");
    expect(formatNumber(92.46, "en", 1)).toBe("92.5");
    expect(formatRatioAsPercent(0.925, "fa")).toBe("۹۲٫۵");
  });
});

describe("formatKpi", () => {
  it("rescales instead of truncating", () => {
    expect(formatKpi(9_999_999, "en")).toMatchObject({ text: "9,999,999", magnitude: "none" });
    expect(formatKpi(12_340_000, "en")).toMatchObject({ text: "12.3", magnitude: "million" });
    expect(formatKpi(2_500_000_000, "fa")).toMatchObject({ text: "۲٫۵", magnitude: "billion" });
    expect(formatKpi(12_340_000, "fa").full).toBe("۱۲٬۳۴۰٬۰۰۰");
  });
});

describe("parseNumericInput", () => {
  it("accepts Persian, Arabic-Indic and pasted grouped input", () => {
    expect(parseNumericInput("۱٬۲۳۴")).toBe("1234");
    expect(parseNumericInput("١٢٣٤٫٥")).toBe("1234.5");
    expect(parseNumericInput("1,234.50")).toBe("1234.50");
    expect(parseNumericInput(" 12 345 ")).toBe("12345");
    expect(parseNumericInput("۰/۷۵")).toBe("0.75");
  });

  it("keeps partial typing and rejects junk", () => {
    expect(parseNumericInput("")).toBe("");
    expect(parseNumericInput("12.")).toBe("12.");
    expect(parseNumericInput(".5")).toBe("0.5");
    expect(parseNumericInput("007")).toBe("7");
    expect(parseNumericInput("12a")).toBeNull();
    expect(parseNumericInput("1.2.3")).toBeNull();
    expect(parseNumericInput("1.5", false)).toBeNull();
  });

  it("round-trips through the display form in both locales", () => {
    for (const locale of ["fa", "en"] as const) {
      for (const raw of ["0", "7", "1234", "1234567.25", "12.", "0.5"]) {
        expect(parseNumericInput(formatRaw(raw, locale))).toBe(raw);
      }
    }
  });

  it("converts to a number only at the edge", () => {
    expect(rawToNumber("1234.5")).toBe(1234.5);
    expect(rawToNumber("")).toBeNaN();
    expect(rawToNumber("12.")).toBeNaN();
    expect(toAsciiDigits("۱۲٣")).toBe("123");
  });
});

describe("caret by digit index", () => {
  it("survives regrouping", () => {
    // Typing "5" after "1٬23|4": 3 digits precede the caret in "1235|4"… → "12٬35|4"
    expect(digitsBefore("۱٬۲۳۵۴", 5)).toBe(4);
    expect(caretAfterDigits("۱۲٬۳۵۴", 4)).toBe(5);
    expect(caretAfterDigits("۱٬۲۳۴", 0)).toBe(0);
    expect(caretAfterDigits("۱٬۲۳۴", 4)).toBe(5);
    expect(digitsBefore("12.5", 3)).toBe(3); // the decimal mark counts as a position
  });
});

describe("threshold unit conversion", () => {
  const config: RepoConfig = {
    embedding: { provider: "hash", model: "char-ngram-512", distance: "cosine", batch_size: 32 },
    chunking: { strategy: "fixed", chunk_size: 1200, overlap: 50, min_chars: 3 },
    normalization: {
      unify_chars: true,
      remove_diacritics: true,
      normalize_digits: true,
      zwnj: "keep",
      lowercase: true,
      strip_punctuation: false,
      collapse_whitespace: true,
    },
    similarity: {
      top_k: 5,
      similar_threshold: 0.755,
      duplicate_threshold: 0.92,
      scope: "self",
      target_repo_ids: [],
      aggregation: "max",
      rerank: "cross_encoder",
      rerank_model: "BAAI/bge-reranker-v2-m3-int8",
      match_floor: null,
    },
  };

  it("stores ratios, edits percents, and converts in one place", () => {
    const draft = configToDraft(config);
    expect(draft.similar_threshold).toBe("75.5");
    expect(draft.duplicate_threshold).toBe("92");
    expect(draft.chunk_size).toBe("1200");
    expect(draftToConfig(draft)).toEqual({ ok: true, config });
  });

  it("reports invalid fields instead of guessing", () => {
    const draft = { ...configToDraft(config), similar_threshold: "95", overlap: "" };
    const result = draftToConfig(draft);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.sort()).toEqual(["overlap", "thresholdOrder"]);
  });

  it("treats an empty match floor as the server default and round-trips a set one", () => {
    expect(configToDraft(config).match_floor).toBe("");
    const set = { ...config, similarity: { ...config.similarity, match_floor: 0.305 } };
    const draft = configToDraft(set);
    expect(draft.match_floor).toBe("30.5");
    expect(draftToConfig(draft)).toEqual({ ok: true, config: set });
    // Whitespace-only is still "unset".
    const blank = draftToConfig({ ...draft, match_floor: "  " });
    expect(blank.ok && blank.config.similarity.match_floor).toBeNull();
  });

  it("rejects a floor out of range, or above similar when there is no second stage", () => {
    const base = configToDraft(config);
    const out = draftToConfig({ ...base, match_floor: "120" });
    expect(!out.ok && out.errors).toEqual(["match_floor"]);

    const noRerank = { ...base, similarity: { ...base.similarity, rerank: "none" as const } };
    const above = draftToConfig({ ...noRerank, match_floor: "80" });
    expect(!above.ok && above.errors).toEqual(["floorAboveSimilar"]);
    // With a second stage the floor and thresholds are on different scales.
    expect(draftToConfig({ ...base, match_floor: "80" }).ok).toBe(true);
  });
});

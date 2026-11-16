/**
 * The single stored-unit ↔ displayed-unit boundary for repo configuration.
 *
 *   thresholds : stored 0..1 ratio   → edited as percent (٪)
 *   sizes      : stored characters   → edited as characters
 *   top_k      : stored count        → edited as results
 *
 * Numeric fields live in the form as raw ASCII strings (what the user typed,
 * minus formatting) and only become numbers here.
 */
import { rawToNumber } from "./format";
import type { RepoConfig } from "./types";

export type NumericField =
  | "batch_size"
  | "chunk_size"
  | "overlap"
  | "min_chars"
  | "top_k"
  | "similar_threshold"
  | "duplicate_threshold";

export type ConfigDraft = Omit<RepoConfig, never> & Record<NumericField, string>;

export type DraftError = NumericField | "thresholdOrder" | "overlapTooLarge";

const LIMITS: Record<NumericField, [number, number]> = {
  batch_size: [1, 512],
  chunk_size: [20, 20000],
  overlap: [0, 5000],
  min_chars: [1, 1000],
  top_k: [1, 100],
  similar_threshold: [0, 100],
  duplicate_threshold: [0, 100],
};

/** 0.755 → "75.5" (at most two decimals, no float noise). */
export function ratioToPercentRaw(ratio: number): string {
  return String(Math.round(ratio * 10000) / 100);
}

export function percentRawToRatio(raw: string): number {
  return Math.round(rawToNumber(raw) * 100) / 10000;
}

export function configToDraft(config: RepoConfig): ConfigDraft {
  return {
    ...structuredClone(config),
    batch_size: String(config.embedding.batch_size),
    chunk_size: String(config.chunking.chunk_size),
    overlap: String(config.chunking.overlap),
    min_chars: String(config.chunking.min_chars),
    top_k: String(config.similarity.top_k),
    similar_threshold: ratioToPercentRaw(config.similarity.similar_threshold),
    duplicate_threshold: ratioToPercentRaw(config.similarity.duplicate_threshold),
  };
}

export function draftToConfig(
  draft: ConfigDraft,
): { ok: true; config: RepoConfig } | { ok: false; errors: DraftError[] } {
  const errors: DraftError[] = [];
  const read = (field: NumericField, integer: boolean): number => {
    const n = rawToNumber(draft[field]);
    const [min, max] = LIMITS[field];
    if (Number.isNaN(n) || n < min || n > max || (integer && !Number.isInteger(n))) {
      errors.push(field);
    }
    return n;
  };

  const batch_size = read("batch_size", true);
  const chunk_size = read("chunk_size", true);
  const overlap = read("overlap", true);
  const min_chars = read("min_chars", true);
  const top_k = read("top_k", true);
  const similarPct = read("similar_threshold", false);
  const duplicatePct = read("duplicate_threshold", false);

  if (!errors.includes("overlap") && !errors.includes("chunk_size") && overlap >= chunk_size) {
    errors.push("overlapTooLarge");
  }
  if (similarPct > duplicatePct) errors.push("thresholdOrder");
  if (errors.length) return { ok: false, errors };

  return {
    ok: true,
    config: {
      embedding: { ...draft.embedding, batch_size },
      chunking: { ...draft.chunking, chunk_size, overlap, min_chars },
      normalization: { ...draft.normalization },
      similarity: {
        ...draft.similarity,
        top_k,
        similar_threshold: percentRawToRatio(draft.similar_threshold),
        duplicate_threshold: percentRawToRatio(draft.duplicate_threshold),
      },
    },
  };
}

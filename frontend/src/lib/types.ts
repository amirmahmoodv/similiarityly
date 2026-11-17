export type Provider = "fastembed" | "openai" | "hash";
export type Distance = "cosine" | "dot" | "euclid";
export type ChunkStrategy = "record" | "fixed" | "sentence" | "paragraph";
export type IngestMode = "check_and_index" | "index_only" | "check_only";
export type RecordStatus = "duplicate" | "similar" | "unique";
export type Scope = "self" | "selected" | "all";

export type RepoConfig = {
  embedding: { provider: Provider; model: string; distance: Distance; batch_size: number };
  chunking: { strategy: ChunkStrategy; chunk_size: number; overlap: number; min_chars: number };
  normalization: {
    unify_chars: boolean;
    remove_diacritics: boolean;
    normalize_digits: boolean;
    zwnj: "keep" | "space" | "remove";
    lowercase: boolean;
    strip_punctuation: boolean;
    collapse_whitespace: boolean;
  };
  similarity: {
    top_k: number;
    /** Stored as a 0..1 ratio; displayed as a percentage (see lib/units.ts). */
    similar_threshold: number;
    duplicate_threshold: number;
    scope: Scope;
    target_repo_ids: string[];
    aggregation: "max" | "mean";
    /** Second stage: a cross-encoder re-scores the top vector hits. */
    rerank: "none" | "cross_encoder";
    rerank_model: string;
  };
};

export type Repo = {
  id: string;
  name: string;
  description: string;
  config: RepoConfig;
  vector_size: number | null;
  needs_reindex: boolean;
  created_at: string;
  source_count: number;
  record_count: number;
  chunk_count: number;
};

export type SourceKind = "excel" | "csv" | "document" | "list" | "paste";

export type Source = {
  id: string;
  repo_id: string;
  name: string;
  kind: SourceKind;
  record_count: number;
  indexed: boolean;
  created_at: string;
  last_job_id: string | null;
};

export type JobStatus = "queued" | "running" | "done" | "failed";

export type Job = {
  id: string;
  repo_id: string;
  source_id: string | null;
  kind: "ingest" | "reindex";
  mode: IngestMode;
  status: JobStatus;
  total: number;
  processed: number;
  /** Stable code, translated under `errors`. */
  error: string | null;
  /** Raw cause, shown under "Technical details". */
  error_detail?: string | null;
  created_at: string;
  finished_at: string | null;
  repo_name: string;
  source_name: string;
};

export type JobSummary = {
  total: number;
  duplicate: number;
  similar: number;
  unique: number;
  similar_threshold: number;
  duplicate_threshold: number;
};

export type RecordItem = {
  id: string;
  ordinal: number;
  text: string;
  meta: Record<string, unknown>;
  chunk_count: number;
  max_score: number;
  match_count: number;
  status: RecordStatus;
};

export type RecordPage = { items: RecordItem[]; total: number; page: number; page_size: number };

export type Match = {
  id: string;
  chunk_index: number;
  chunk_text: string;
  score: number;
  /** First-stage score; null unless a second stage produced `score`. */
  vector_score: number | null;
  matched_repo_id: string;
  matched_text: string;
  matched_repo_name: string;
  matched_source_name: string;
};

export type Preview = {
  kind: "tabular" | "document";
  columns: string[];
  rows: string[][];
  total_rows: number;
  sheets: string[];
  excerpt: string;
  char_count: number;
};

export type Meta = {
  providers: { id: Provider; available: boolean; models: string[] }[];
  rerankers: { available: boolean; models: string[] };
  defaults: RepoConfig;
  qdrant_mode: "server" | "embedded" | "memory";
};

export type QdrantMode = "server" | "embedded" | "memory";
export type LLMProvider = "openai" | "anthropic";

export type AppSettings = {
  qdrant: { mode: QdrantMode; url: string; api_key_set: boolean };
  /** OpenAI-compatible endpoint used by the "openai" embedding provider; "" = OpenAI. */
  embeddings: { base_url: string; api_key_set: boolean };
  llm: { provider: LLMProvider; base_url: string; model: string; api_key_set: boolean };
};

/** `api_key`: omitted/null keeps the saved key, "" clears it. */
export type QdrantSettingsInput = {
  mode: "server" | "embedded";
  url: string;
  api_key?: string | null;
};

export type EmbeddingsSettingsInput = {
  base_url: string;
  api_key?: string | null;
};

export type LLMSettingsInput = {
  provider: LLMProvider;
  base_url: string;
  model: string;
  api_key?: string | null;
};

export type ConnectionTest = {
  ok: boolean;
  latency_ms: number;
  /** Stable code, translated under `settings.errors`. */
  error: string | null;
  detail: string | null;
  version: string | null;
  collections: number | null;
  /** The app's qdrant-client version, to compare with the server's. */
  client_version?: string | null;
  /** Qdrant: each request the check made, timed. */
  steps?: { name: string; ok: boolean; ms: number; error: string | null }[];
  models: string[];
  model_found: boolean | null;
};

export type Stats = {
  repos: number;
  sources: number;
  records: number;
  chunks: number;
  matches: number;
};

export type SearchHit = {
  score: number;
  vector_score: number | null;
  text: string;
  record_id: string;
  chunk_index: number;
  source_id: string;
  source_name: string;
};

/** `id` is stable; `chunk_index` shifts down when an earlier chunk is deleted. */
export type Chunk = { id: string; chunk_index: number; text: string };

/** One indexed record; `chunks` is a prefix when `chunk_count` is larger. */
export type RecordChunks = {
  record_id: string;
  ordinal: number;
  source_id: string;
  source_name: string;
  chunk_count: number;
  chunks: Chunk[];
  /** Set by a text search: `chunks` then holds matching chunks only. */
  match_count: number | null;
};

/** `total` counts records, not chunks. */
export type ChunkPage = {
  items: RecordChunks[];
  total: number;
  page: number;
  page_size: number;
  /** A search matched more chunks than the server scans. */
  truncated: boolean;
};

export type IndexStatus = {
  searchable: boolean;
  /** Stable problem code, translated under `search.problems`. */
  problem: string | null;
  exists: boolean;
  points: number;
  vector_size: number | null;
  distance: string | null;
  configured_distance: string;
  collection_status: string | null;
  indexed_fields: string[];
  mode: "server" | "embedded" | "memory";
};

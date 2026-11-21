import type {
  AppSettings,
  Chunk,
  ChunkPage,
  ConnectionTest,
  EmbeddingsSettingsInput,
  LLMSettingsInput,
  QdrantSettingsInput,
  IndexStatus,
  IngestMode,
  Job,
  JobSummary,
  Match,
  Meta,
  Preview,
  RecordPage,
  RecordStatus,
  RepairResult,
  Repo,
  RepoConfig,
  SearchHit,
  Source,
  Stats,
} from "./types";

declare global {
  interface Window {
    /** Set by /config.js, which the container writes from API_URL at start. */
    __SIM_CONFIG__?: { apiUrl?: string };
  }
}

/** "" = same origin (nginx or the Vite dev proxy forwards /api). */
function apiOrigin(): string {
  const url = typeof window === "undefined" ? "" : (window.__SIM_CONFIG__?.apiUrl ?? "");
  return url.trim().replace(/\/+$/, "");
}

const BASE = `${apiOrigin()}/api/v1`;

/**
 * `code` is the backend's stable error code; the UI translates it.
 * `detail` is the raw cause some errors carry, shown under "Technical details".
 */
export class ApiError extends Error {
  status: number;
  code: string;
  detail: string;

  constructor(status: number, code: string, detail = "") {
    super(code);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

// ---- Access token -----------------------------------------------------------
// Sent as a header (never a cookie), so other sites cannot make the browser use it.

const TOKEN_KEY = "similarityly.apiToken";
/** Fired when the API answers 401, so the UI can ask for a token. */
export const UNAUTHORIZED_EVENT = "similarityly:unauthorized";

export function getApiToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setApiToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the token lasts until reload */
  }
  memoryToken = token;
}

let memoryToken = getApiToken();

async function send(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (memoryToken) headers.set("Authorization", `Bearer ${memoryToken}`);
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  if (!res.ok) {
    let code = "unknown_error";
    let detail = "";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") code = body.detail;
      else if (typeof body.detail?.code === "string") {
        // {code, message}: a translatable code plus the server's raw message.
        code = body.detail.code;
        detail = typeof body.detail.message === "string" ? body.detail.message : "";
      } else if (res.status === 422) code = "validation_error";
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export type IngestInput = {
  mode: IngestMode;
  name: string;
} & (
  | { kind: "text"; split: "lines" | "paragraphs" | "whole"; text: string }
  | {
      kind: "file";
      file: File;
      options: {
        sheet?: string;
        has_header?: boolean;
        text_columns?: string[];
        /** Names each record; kept out of the compared text. */
        label_column?: string | null;
      };
    }
);

/** "wide": candidates pivoted into columns. "long": one row per candidate. */
export type ExportLayout = "wide" | "long";

export type XlsxExportOptions = {
  layout: ExportLayout;
  /** Candidates written per record (1..100). */
  candidates: number;
  status: RecordStatus | "all";
  /** Language of the sheet's headers and status names. */
  lang: "fa" | "en";
};

/** Fetched (not a plain link) so the access token goes with it. */
async function download(path: string, filename: string): Promise<void> {
  const res = await send(path);
  if (!res.ok) {
    const code =
      res.status === 401 ? "unauthorized" : res.status === 422 ? "validation_error" : "unknown_error";
    throw new ApiError(res.status, code);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type RepoPatch =Partial<{ name: string; description: string; config: RepoConfig }>;

export const api = {
  meta: () => request<Meta>("/meta"),
  stats: () => request<Stats>("/stats"),

  repos: () => request<Repo[]>("/repos"),
  repo: (id: string) => request<Repo>(`/repos/${id}`),
  createRepo: (body: { name: string; description: string; config: RepoConfig }) =>
    request<Repo>("/repos", json("POST", body)),
  updateRepo: (id: string, body: RepoPatch) => request<Repo>(`/repos/${id}`, json("PATCH", body)),
  deleteRepo: (id: string) => request<void>(`/repos/${id}`, { method: "DELETE" }),
  indexStatus: (id: string) => request<IndexStatus>(`/repos/${id}/index`),
  search: (id: string, query: string, top_k: number) =>
    request<SearchHit[]>(`/repos/${id}/search`, json("POST", { query, top_k })),
  chunks: (id: string, sourceId: string | null, query: string, page: number, pageSize: number) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (sourceId) params.set("source_id", sourceId);
    if (query) params.set("q", query);
    return request<ChunkPage>(`/repos/${id}/chunks?${params}`);
  },
  recordChunks: (recordId: string, offset: number, limit: number) =>
    request<Chunk[]>(`/records/${recordId}/chunks?offset=${offset}&limit=${limit}`),
  addChunk: (recordId: string, text: string) =>
    request<Chunk>(`/records/${recordId}/chunks`, json("POST", { text })),
  updateChunk: (recordId: string, chunkId: string, text: string) =>
    request<Chunk>(`/records/${recordId}/chunks/${chunkId}`, json("PATCH", { text })),
  deleteChunk: (recordId: string, chunkId: string) =>
    request<void>(`/records/${recordId}/chunks/${chunkId}`, { method: "DELETE" }),
  reindex: (id: string) => request<Job>(`/repos/${id}/reindex`, { method: "POST" }),
  repair: (id: string) => request<RepairResult>(`/repos/${id}/repair`, { method: "POST" }),

  sources: (repoId: string) => request<Source[]>(`/repos/${repoId}/sources`),
  deleteSource: (id: string) => request<void>(`/sources/${id}`, { method: "DELETE" }),

  preview: (file: File, sheet?: string, hasHeader = true) => {
    const form = new FormData();
    form.set("file", file);
    if (sheet) form.set("sheet", sheet);
    form.set("has_header", String(hasHeader));
    return request<Preview>("/sources/preview", { method: "POST", body: form });
  },

  ingest: (repoId: string, input: IngestInput) => {
    const form = new FormData();
    form.set("input_kind", input.kind);
    form.set("mode", input.mode);
    form.set("name", input.name);
    if (input.kind === "text") {
      form.set("split", input.split);
      form.set("text", input.text);
    } else {
      form.set("file", input.file);
      form.set("options", JSON.stringify(input.options));
    }
    return request<Job>(`/repos/${repoId}/ingest`, { method: "POST", body: form });
  },

  jobs: (repoId?: string, limit = 20) =>
    request<Job[]>(`/jobs?limit=${limit}${repoId ? `&repo_id=${repoId}` : ""}`),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  jobSummary: (id: string) => request<JobSummary>(`/jobs/${id}/summary`),
  jobRecords: (id: string, status: RecordStatus | "all", page: number, pageSize: number) =>
    request<RecordPage>(
      `/jobs/${id}/records?status=${status}&page=${page}&page_size=${pageSize}&sort=score`,
    ),
  matches: (recordId: string) => request<Match[]>(`/records/${recordId}/matches`),
  exportCsv: (jobId: string) =>
    download(`/jobs/${encodeURIComponent(jobId)}/export.csv`, `similarity-${jobId}.csv`),
  exportXlsx: (jobId: string, options: XlsxExportOptions) => {
    const params = new URLSearchParams({
      layout: options.layout,
      candidates: String(options.candidates),
      status: options.status,
      lang: options.lang,
    });
    return download(
      `/jobs/${encodeURIComponent(jobId)}/export.xlsx?${params}`,
      `similarity-${jobId}.xlsx`,
    );
  },

  settings: () => request<AppSettings>("/settings"),
  testQdrant: (body: QdrantSettingsInput) =>
    request<ConnectionTest>("/settings/qdrant/test", json("POST", body)),
  saveQdrant: (body: QdrantSettingsInput) =>
    request<AppSettings>("/settings/qdrant", json("PUT", body)),
  testEmbeddings: (body: EmbeddingsSettingsInput) =>
    request<ConnectionTest>("/settings/embeddings/test", json("POST", body)),
  saveEmbeddings: (body: EmbeddingsSettingsInput) =>
    request<AppSettings>("/settings/embeddings", json("PUT", body)),
  testLLM: (body: LLMSettingsInput) =>
    request<ConnectionTest>("/settings/llm/test", json("POST", body)),
  saveLLM: (body: LLMSettingsInput) => request<AppSettings>("/settings/llm", json("PUT", body)),
};

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Provider = Literal["fastembed", "openai", "hash"]
Distance = Literal["cosine", "dot", "euclid"]
ChunkStrategy = Literal["record", "fixed", "sentence", "paragraph"]
IngestMode = Literal["check_and_index", "index_only", "check_only"]
RecordStatus = Literal["duplicate", "similar", "unique"]


# ---- Tunable repo configuration -------------------------------------------


class EmbeddingConfig(BaseModel):
    provider: Provider = "hash"
    model: str = "char-ngram-512"
    distance: Distance = "cosine"
    batch_size: int = Field(32, ge=1, le=512)


class ChunkingConfig(BaseModel):
    # "record" embeds each record as one chunk; the others split long text.
    strategy: ChunkStrategy = "record"
    chunk_size: int = Field(500, ge=20, le=20000)  # characters
    overlap: int = Field(50, ge=0, le=5000)  # characters
    min_chars: int = Field(3, ge=1, le=1000)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self):
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        return self


class NormalizationConfig(BaseModel):
    unify_chars: bool = True  # ي/ك -> ی/ک, NFKC
    remove_diacritics: bool = True  # harakat + tatweel
    normalize_digits: bool = True  # ۰-۹ / ٠-٩ -> 0-9
    zwnj: Literal["keep", "space", "remove"] = "keep"
    lowercase: bool = True
    strip_punctuation: bool = False
    collapse_whitespace: bool = True


class SimilarityConfig(BaseModel):
    top_k: int = Field(5, ge=1, le=100)
    similar_threshold: float = Field(0.75, ge=0, le=1)
    duplicate_threshold: float = Field(0.92, ge=0, le=1)
    # Which repos a new record is compared against (its own repo is always included).
    scope: Literal["self", "selected", "all"] = "self"
    target_repo_ids: list[str] = Field([], max_length=500)
    # How per-chunk best scores roll up into one record score.
    aggregation: Literal["max", "mean"] = "max"
    # Second stage: re-score the top_k vector hits with a cross-encoder. Its
    # score replaces the vector score, so thresholds then apply to it.
    rerank: Literal["none", "cross_encoder"] = "none"
    rerank_model: str = Field("BAAI/bge-reranker-v2-m3-int8", min_length=1, max_length=300)
    # Hits whose vector score is below this are not stored as matches. None
    # uses the server's SIM_MATCH_STORE_FLOOR. Applied when a check runs, so
    # changing it affects new checks only.
    match_floor: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _ordered_thresholds(self):
        if self.duplicate_threshold < self.similar_threshold:
            raise ValueError("duplicate_threshold must be >= similar_threshold")
        # Without a second stage the floor and thresholds share one scale: a
        # floor above "similar" would hide the matches of similar records.
        if (
            self.rerank == "none"
            and self.match_floor is not None
            and self.match_floor > self.similar_threshold
        ):
            raise ValueError("match_floor must be <= similar_threshold")
        return self


class RepoConfig(BaseModel):
    embedding: EmbeddingConfig = EmbeddingConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    normalization: NormalizationConfig = NormalizationConfig()
    similarity: SimilarityConfig = SimilarityConfig()

    def index_signature(self) -> str:
        """Everything that changes stored vectors. Similarity settings do not."""
        e = self.embedding
        return "|".join(
            [
                e.provider,
                e.model,
                e.distance,
                self.chunking.model_dump_json(),
                self.normalization.model_dump_json(),
            ]
        )


# ---- API I/O ---------------------------------------------------------------


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RepoCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    config: RepoConfig = RepoConfig()


class RepoUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    config: RepoConfig | None = None


class RepoOut(ORM):
    id: str
    name: str
    description: str
    config: RepoConfig
    vector_size: int | None
    needs_reindex: bool
    created_at: datetime
    source_count: int = 0
    record_count: int = 0
    chunk_count: int = 0


class SourceOut(ORM):
    id: str
    repo_id: str
    name: str
    kind: str
    record_count: int
    indexed: bool
    created_at: datetime
    last_job_id: str | None = None


class JobOut(ORM):
    id: str
    repo_id: str
    source_id: str | None
    kind: str
    mode: str
    status: str
    total: int
    processed: int
    error: str | None
    error_detail: str | None = None
    created_at: datetime
    finished_at: datetime | None
    repo_name: str = ""
    source_name: str = ""


class JobSummary(BaseModel):
    total: int
    duplicate: int
    similar: int
    unique: int
    similar_threshold: float
    duplicate_threshold: float


class RecordOut(BaseModel):
    id: str
    ordinal: int
    text: str
    label: str = ""
    meta: dict
    chunk_count: int
    max_score: float
    match_count: int
    status: RecordStatus


class RecordPage(BaseModel):
    items: list[RecordOut]
    total: int
    page: int
    page_size: int


class MatchOut(ORM):
    id: str
    chunk_index: int
    chunk_text: str
    score: float
    vector_score: float | None = None  # first-stage score, when a second stage ran
    matched_repo_id: str
    matched_source_id: str
    matched_record_id: str
    matched_chunk_index: int
    matched_text: str
    matched_label: str = ""
    matched_repo_name: str = ""
    matched_source_name: str = ""


class PreviewOut(BaseModel):
    kind: Literal["tabular", "document"]
    columns: list[str] = []
    rows: list[list[str]] = []
    total_rows: int = 0
    sheets: list[str] = []
    excerpt: str = ""
    char_count: int = 0


class ProviderInfo(BaseModel):
    id: Provider
    available: bool
    models: list[str]


class RerankerInfo(BaseModel):
    available: bool
    models: list[str]


class MetaOut(BaseModel):
    providers: list[ProviderInfo]
    rerankers: RerankerInfo
    defaults: RepoConfig
    qdrant_mode: Literal["server", "embedded", "memory"]
    # What a repo with no match_floor of its own uses.
    match_store_floor: float


class StatsOut(BaseModel):
    repos: int
    sources: int
    records: int
    chunks: int
    matches: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    top_k: int = Field(10, ge=1, le=100)


class SearchHit(BaseModel):
    score: float  # 0..1 similarity
    vector_score: float | None = None  # first-stage score, when a second stage ran
    text: str
    record_id: str
    label: str = ""  # the chunk's record label, "" when its load had no label column
    chunk_index: int
    source_id: str
    source_name: str = ""


class ChunkOut(BaseModel):
    id: str  # Qdrant point id; stable while chunk_index shifts on deletion
    chunk_index: int
    text: str


class ChunkUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty_text")
        return value


class RecordChunks(BaseModel):
    """One indexed record with the first few of its stored chunks."""

    record_id: str
    ordinal: int
    label: str = ""
    source_id: str
    source_name: str = ""
    chunk_count: int  # chunks stored for the record; `chunks` may be a prefix
    chunks: list[ChunkOut]
    # Set when the listing was searched: `chunks` then holds matching chunks
    # only (the first few), and this counts all of the record's matches.
    match_count: int | None = None


class ChunkPage(BaseModel):
    items: list[RecordChunks]
    total: int  # records
    page: int
    page_size: int
    truncated: bool = False  # a search matched more chunks than were scanned
    # Records of this page left out because Qdrant cannot decode their stored
    # data; `POST /repos/{id}/repair` removes them.
    unreadable: int = 0


class RepairOut(BaseModel):
    """What a repair removed: entries whose stored data could not be read."""

    records_removed: int = 0
    matches_removed: int = 0


class IndexStatus(BaseModel):
    """Whether a repo's Qdrant collection can be searched right now."""

    searchable: bool = False
    problem: str | None = None  # stable code, translated by the UI
    exists: bool = False
    points: int = 0
    vector_size: int | None = None
    distance: str | None = None
    configured_distance: str
    collection_status: str | None = None
    indexed_fields: list[str] = []
    mode: str


# ---- Connection settings ---------------------------------------------------

QdrantMode = Literal["server", "embedded", "memory"]
LLMProvider = Literal["openai", "anthropic"]


class QdrantSettingsOut(BaseModel):
    mode: QdrantMode
    url: str
    api_key_set: bool


class LLMSettingsOut(BaseModel):
    provider: LLMProvider
    base_url: str
    model: str
    api_key_set: bool


class EmbeddingsSettingsOut(BaseModel):
    base_url: str
    api_key_set: bool


class SettingsOut(BaseModel):
    qdrant: QdrantSettingsOut
    embeddings: EmbeddingsSettingsOut
    llm: LLMSettingsOut


class QdrantSettingsIn(BaseModel):
    mode: Literal["server", "embedded"]
    url: str = Field("", max_length=2000)
    # None keeps the saved key, "" clears it. Keys are never sent back to the UI.
    api_key: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _server_needs_url(self):
        self.url = self.url.strip()
        if self.mode == "server" and not self.url.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return self


class LLMSettingsIn(BaseModel):
    provider: LLMProvider
    base_url: str = Field("", max_length=2000)
    api_key: str | None = Field(None, max_length=2000)
    model: str = Field("", max_length=300)

    @model_validator(mode="after")
    def _valid_url(self):
        self.base_url = self.base_url.strip()
        self.model = self.model.strip()
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return self


class EmbeddingsSettingsIn(BaseModel):
    """The OpenAI-compatible endpoint used by the "openai" embedding provider."""

    base_url: str = Field("", max_length=2000)  # empty = OpenAI's default
    api_key: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _valid_url(self):
        self.base_url = self.base_url.strip()
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return self


class ConnectionStep(BaseModel):
    """One timed request of a connection check."""

    name: str  # stable id, translated by the UI
    ok: bool
    ms: int
    error: str | None = None


class ConnectionTest(BaseModel):
    ok: bool
    latency_ms: int = 0
    error: str | None = None  # stable code, translated by the UI
    detail: str | None = None
    version: str | None = None  # Qdrant
    collections: int | None = None  # Qdrant
    client_version: str | None = None  # Qdrant: the app's qdrant-client
    steps: list[ConnectionStep] = []  # Qdrant: each request, timed
    models: list[str] = []  # LLM
    model_found: bool | None = None  # LLM; None when no model was given

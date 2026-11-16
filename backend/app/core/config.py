from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SIM_", extra="ignore")

    data_dir: Path = Path("data")

    # Empty url -> embedded on-disk Qdrant under data_dir (dev only, single process).
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_in_memory: bool = False
    collection_prefix: str = "sim_"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None

    # Chat/completion LLM. "openai" = any OpenAI-compatible API (OpenAI, Ollama,
    # vLLM, OpenRouter, ...); "anthropic" = Claude via the Anthropic SDK.
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_base_url: str = ""  # empty = the provider's default endpoint
    llm_api_key: str | None = None
    llm_model: str = ""

    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_mb: int = 50

    # Shared access token. When set, every /api/ request must carry
    # "Authorization: Bearer <token>". Leave empty only on a trusted, local-only
    # setup: without it anyone who can reach the API can read and delete data.
    api_token: str | None = None

    # Run jobs in the request thread (tests).
    jobs_inline: bool = False
    # Records embedded per batch inside a job.
    job_batch_size: int = 32
    # Hits below this similarity are never stored, so thresholds can be tuned
    # after the fact for anything above it.
    match_store_floor: float = 0.3

    @property
    def runtime_settings_path(self) -> Path:
        """Connection settings saved from the UI; they override the SIM_ env vars."""
        return self.data_dir / "settings.json"

    @property
    def models_dir(self) -> Path:
        """Downloaded local models. The library default is the temp folder,
        which gets cleaned and would force a fresh download."""
        return self.data_dir / "models"

    @property
    def qdrant_mode(self) -> str:
        if self.qdrant_in_memory:
            return "memory"
        return "server" if self.qdrant_url else "embedded"

    @property
    def legacy_sqlite_path(self) -> Path:
        """Pre-Qdrant metadata file; imported once on startup if present."""
        return self.data_dir / "similarityly.db"

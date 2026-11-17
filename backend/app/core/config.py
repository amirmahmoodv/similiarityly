import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Connections are configured on the Settings page (saved to settings.json), never
# through the environment: SIM_ variables for these fields are ignored on purpose.
UI_ONLY_FIELDS = frozenset(
    {
        "qdrant_url",
        "qdrant_api_key",
        "openai_base_url",
        "openai_api_key",
        "llm_provider",
        "llm_base_url",
        "llm_api_key",
        "llm_model",
    }
)


class _WithoutUIFields(PydanticBaseSettingsSource):
    """Wraps an env/.env source and drops the UI-only fields from what it returns."""

    def __init__(self, inner: PydanticBaseSettingsSource):
        super().__init__(inner.settings_cls)
        self._inner = inner

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[None, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict:
        return {k: v for k, v in self._inner().items() if k not in UI_ONLY_FIELDS}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SIM_", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Constructor arguments (tests) still set any field.
        return (
            init_settings,
            _WithoutUIFields(env_settings),
            _WithoutUIFields(dotenv_settings),
            file_secret_settings,
        )

    data_dir: Path = Path("data")

    # Qdrant server used until one is saved on the Settings page (docker-compose
    # points it at the bundled service). Empty = embedded on-disk Qdrant.
    default_qdrant_url: str | None = None

    # Empty url -> embedded on-disk Qdrant under data_dir (dev only, single process).
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    # Dev/test only: a throwaway in-memory Qdrant. Saving a Qdrant in the UI turns it off.
    qdrant_in_memory: bool = False
    # Seconds per request to a Qdrant server. qdrant-client's default of 5 s is
    # too short for a remote server: switching to one creates collections and
    # waits for payload indexes, and each of those calls can take longer.
    qdrant_timeout: int = Field(60, ge=1, le=600)
    collection_prefix: str = "sim_"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None

    # Chat/completion LLM. "openai" = any OpenAI-compatible API (OpenAI, Ollama,
    # vLLM, OpenRouter, ...); "anthropic" = Claude via the Anthropic SDK.
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_base_url: str = ""  # empty = the provider's default endpoint
    llm_api_key: str | None = None
    llm_model: str = ""

    # Browser origins allowed to call the API from another origin, e.g. the UI at
    # https://sim.example.com calling https://api.sim.example.com. A JSON list or a
    # comma-separated string. Not needed when the UI reaches the API under /api.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    max_upload_mb: int = 50

    # Shared access token. When set, every /api/ request must carry
    # "Authorization: Bearer <token>". Leave empty only on a trusted, local-only
    # setup: without it anyone who can reach the API can read and delete data.
    api_token: str | None = None

    # Serve /docs and /openapi.json. Off by default: they map every endpoint.
    enable_docs: bool = False
    # Start even though SIM_CORS_ORIGINS names a public origin and no token is
    # set: only when an authenticating proxy in front of the API protects it.
    allow_public_without_token: bool = False

    # Run jobs in the request thread (tests).
    jobs_inline: bool = False
    # Records embedded per batch inside a job.
    job_batch_size: int = 32
    # Hits below this similarity are never stored, so thresholds can be tuned
    # after the fact for anything above it.
    match_store_floor: float = 0.3

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value):
        if isinstance(value, str):
            text = value.strip()
            value = json.loads(text) if text.startswith("[") else text.split(",")
        # A browser's Origin header never ends in "/", so "https://x/" would never match.
        return [str(o).strip().rstrip("/") for o in value if str(o).strip()]

    @model_validator(mode="after")
    def _apply_default_qdrant(self):
        # Saved UI values are applied later with model_copy, so they still win.
        if self.qdrant_url is None and self.default_qdrant_url:
            self.qdrant_url = self.default_qdrant_url
        return self

    @property
    def runtime_settings_path(self) -> Path:
        """Connection settings saved from the Settings page (the only place they are set)."""
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

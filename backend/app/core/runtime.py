"""Connection settings edited from the UI.

They live in `<data_dir>/settings.json`, not in Qdrant: the Qdrant connection
itself is one of them, and metadata is stored in Qdrant. Saved values override
the code defaults; connection SIM_ environment variables are ignored (see
`UI_ONLY_FIELDS` in config.py).
"""

import json
import logging
import os
import threading
from typing import Any

from app.core.config import Settings

log = logging.getLogger("similarityly")

# Only these Settings fields may be overridden from the UI.
EDITABLE = {
    "qdrant_url",
    "qdrant_api_key",
    "qdrant_in_memory",
    "openai_base_url",
    "openai_api_key",
    "llm_provider",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
}

_lock = threading.Lock()


def load_overrides(settings: Settings) -> dict[str, Any]:
    path = settings.runtime_settings_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable %s: %s", path, exc)
        return {}
    return {k: v for k, v in data.items() if k in EDITABLE} if isinstance(data, dict) else {}


def apply_overrides(settings: Settings) -> Settings:
    overrides = load_overrides(settings)
    return settings.model_copy(update=overrides) if overrides else settings


def save_overrides(settings: Settings, changes: dict[str, Any]) -> Settings:
    """Merge `changes` into the file and return settings with them applied."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    with _lock:
        data = load_overrides(settings) | changes
        path = settings.runtime_settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # holds API keys
        except OSError:
            pass
        os.replace(tmp, path)
    return settings.model_copy(update=changes)

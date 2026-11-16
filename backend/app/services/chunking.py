"""Split a record's text into chunks according to the repo's chunking config."""

import re

from app.schemas import ChunkingConfig

_SENTENCE = re.compile(r"(?<=[.!?؟؛…])\s+|\n+")
_PARAGRAPH = re.compile(r"\n\s*\n")


def _fixed(text: str, size: int, overlap: int) -> list[str]:
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(len(text) - overlap, 1), step)]


def _pack(units: list[str], size: int, overlap: int, joiner: str) -> list[str]:
    """Greedily pack units up to `size` chars, carrying trailing units as overlap."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for unit in units:
        if len(unit) > size:  # a single oversized unit falls back to fixed windows
            if current:
                chunks.append(joiner.join(current))
                current, length = [], 0
            chunks.extend(_fixed(unit, size, overlap))
            continue
        added = len(unit) + (len(joiner) if current else 0)
        if current and length + added > size:
            chunks.append(joiner.join(current))
            carried: list[str] = []
            carried_len = 0
            for prev in reversed(current):
                if carried_len + len(prev) > overlap:
                    break
                carried.insert(0, prev)
                carried_len += len(prev) + len(joiner)
            current = carried
            length = len(joiner.join(current))
            added = len(unit) + (len(joiner) if current else 0)
        current.append(unit)
        length += added
    if current:
        chunks.append(joiner.join(current))
    return chunks


def chunk_text(text: str, cfg: ChunkingConfig) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if cfg.strategy == "record":
        chunks = [text]
    elif cfg.strategy == "fixed":
        chunks = _fixed(text, cfg.chunk_size, cfg.overlap)
    elif cfg.strategy == "sentence":
        units = [u.strip() for u in _SENTENCE.split(text) if u and u.strip()]
        chunks = _pack(units, cfg.chunk_size, cfg.overlap, " ")
    else:  # paragraph
        units = [u.strip() for u in _PARAGRAPH.split(text) if u.strip()]
        if len(units) == 1:
            units = [u.strip() for u in text.split("\n") if u.strip()]
        chunks = _pack(units, cfg.chunk_size, cfg.overlap, "\n")
    return [c.strip() for c in chunks if len(c.strip()) >= cfg.min_chars]

"""Persian-aware text normalization applied right before embedding.

Stored/displayed text is never altered; only the string handed to the embedder is.
"""

import re
import unicodedata

from app.schemas import NormalizationConfig

ZWNJ = "‌"

_ARABIC_TO_PERSIAN = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
    }
)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DIACRITICS = re.compile("[ً-ٰٟـ]")
_PUNCT = re.compile(rf"[^\w\s{ZWNJ}]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text: str, cfg: NormalizationConfig) -> str:
    if cfg.unify_chars:
        text = unicodedata.normalize("NFKC", text).translate(_ARABIC_TO_PERSIAN)
    if cfg.remove_diacritics:
        text = _DIACRITICS.sub("", text)
    if cfg.normalize_digits:
        text = text.translate(_DIGITS)
    if cfg.zwnj == "space":
        text = text.replace(ZWNJ, " ")
    elif cfg.zwnj == "remove":
        text = text.replace(ZWNJ, "")
    if cfg.lowercase:
        text = text.lower()
    if cfg.strip_punctuation:
        text = _PUNCT.sub(" ", text)
    if cfg.collapse_whitespace:
        text = _SPACES.sub(" ", text).strip()
    return text

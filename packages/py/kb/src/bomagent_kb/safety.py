"""Treat document text as data (SECURITY.md: prompt injection from datasheets).

``sanitize`` removes control characters that can hide text from reviewers;
``looks_like_injection`` flags chunks that address the model instead of describing a
component. Flagged chunks are still stored (they may contain real data) but retrieval
ranks them last and agents receive them marked as suspicious.
"""

from __future__ import annotations

import re
import unicodedata

_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (the )?(system|previous) (prompt|instructions)"
    r"|you are now|act as (an?|the) (assistant|ai|system)"
    r"|system prompt|developer message|<\s*/?\s*(system|assistant|instructions?)\s*>"
    r"|(output|return|respond with) (only )?(the )?(json|mpn) [^.]{0,40}(instead|regardless)"
    r"|zignoruj (poprzednie|wcześniejsze) (polecenia|instrukcje))",
    re.IGNORECASE,
)


def sanitize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return _CONTROL.sub("", text)


def looks_like_injection(text: str) -> bool:
    # irregular spacing and line breaks must not hide a phrase ("ignore  previous\ninstructions")
    return bool(_INJECTION.search(" ".join(text.split())))


MAX_FREE_TEXT = 2000


def clean_free_text(text: str, *, limit: int = MAX_FREE_TEXT) -> str:
    """Normalise and size-cap free text produced by an LLM before it is stored or shown
    (``rationale``, finding messages): Unicode NFC, no hidden control characters, collapsed
    whitespace, at most ``limit`` characters (ending in an ellipsis when cut)."""
    cleaned = " ".join(sanitize(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 1, 0)].rstrip() + "\u2026"

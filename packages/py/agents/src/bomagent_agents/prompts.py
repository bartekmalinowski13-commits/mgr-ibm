"""Versioned prompts. Each prompt is a Markdown file with front matter (``id``,
``version``); the effective version recorded in provenance is ``<version>+<sha8>`` so a
silent edit of the text changes the recorded version (experiment reproducibility)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    text: str

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    @property
    def full_version(self) -> str:
        return f"{self.version}+{self.sha[:8]}"


def _parse(raw: str) -> Prompt:
    if not raw.startswith("---\n"):
        raise ValueError("prompt file without front matter")
    head, body = raw[4:].split("\n---\n", 1)
    meta = dict(line.split(":", 1) for line in head.strip().splitlines())
    return Prompt(meta["id"].strip(), meta["version"].strip(), body.strip())


@cache
def load_prompt(prompt_id: str, version: str = "1") -> Prompt:
    raw = (
        resources.files(__package__)
        .joinpath(f"prompts/{prompt_id}.v{version}.md")
        .read_text(encoding="utf-8")
    )
    prompt = _parse(raw)
    if prompt.id != prompt_id:
        raise ValueError(f"prompt file id mismatch: {prompt.id} != {prompt_id}")
    return prompt


def data_block(name: str, payload: str) -> str:
    """Wrap untrusted content; the closing tag inside the payload is neutralised."""
    safe = payload.replace("</data>", "<\\/data>")
    return f'<data name="{name}">\n{safe}\n</data>'

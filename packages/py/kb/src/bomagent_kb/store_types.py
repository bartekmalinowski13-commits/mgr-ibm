"""Value types shared by the knowledge-base store and the document registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    GLOBAL = "global"
    TENANT = "tenant"


@dataclass(frozen=True)
class DocumentMeta:
    title: str
    mime_type: str
    sha256: str
    size_bytes: int
    kind: str = "datasheet"
    manufacturer: str = ""
    source_uri: str = ""
    object_key: str | None = None

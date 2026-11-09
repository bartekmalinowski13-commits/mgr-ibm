"""Format parser plugin contract (FORMATS.md, ADR-0009)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from bomagent_bom.model import ParsedDesign, SourceFile

MAX_FILE_BYTES = 64 * 1024 * 1024


class ParseError(ValueError):
    """The file is recognised but cannot be parsed (corrupt, unsupported version...)."""

    def __init__(self, message: str, *, code: str = "parse.failed") -> None:
        super().__init__(message)
        self.code = code


class UnsupportedFormatError(ParseError):
    """No parser handles the input; ``code`` maps to a localised UI hint."""


@dataclass(frozen=True)
class FileRef:
    name: str
    data: bytes = field(repr=False)

    @classmethod
    def from_path(cls, path: str | Path) -> FileRef:
        p = Path(path)
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ParseError(
                f"{p.name}: file larger than {MAX_FILE_BYTES} bytes", code="file.too_large"
            )
        return cls(p.name, p.read_bytes())

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def text(self) -> str:
        try:
            return self.data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParseError(f"{self.name}: not valid UTF-8 text", code="file.encoding") from exc

    def source(self) -> SourceFile:
        return SourceFile(name=self.name, sha256=self.sha256, size_bytes=len(self.data))


@runtime_checkable
class FormatParser(Protocol):
    format_id: str
    version: str

    def sniff(self, file: FileRef) -> float:
        """0..1 - how likely this file is in the parser's format."""
        ...

    def parse(self, files: list[FileRef]) -> ParsedDesign: ...

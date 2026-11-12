"""Minimal, safe S-expression reader for KiCad and EDIF files.

Iterative (no recursion), with limits on input size, nesting depth and token count, so a
malicious file cannot exhaust the stack or memory (SECURITY.md: untrusted files).
Atoms are returned as :class:`Atom` (``str`` subclass), quoted strings as plain ``str``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Union

MAX_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 512
# ~10x a large real schematic; keeps worst-case memory of the object tree bounded
MAX_TOKENS = 3_000_000


class SexprError(ValueError):
    pass


class Atom(str):
    """Unquoted token (keyword, number, yes/no)."""

    __slots__ = ()


SExpr = Union[str, "SList"]


class SList(list[SExpr]):
    """A parenthesised list; ``head`` is its first atom (e.g. ``symbol``)."""

    @property
    def head(self) -> str:
        return self[0] if self and isinstance(self[0], Atom) else ""

    def children(self, name: str) -> Iterator[SList]:
        for item in self[1:]:
            if isinstance(item, SList) and item.head == name:
                yield item

    def child(self, name: str) -> SList | None:
        return next(self.children(name), None)

    def value(self, name: str, default: str = "") -> str:
        """Second element of the first child ``(name value ...)``."""
        c = self.child(name)
        if c is None or len(c) < 2 or isinstance(c[1], SList):
            return default
        return str(c[1])


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def _read_string(text: str, i: int) -> tuple[str, int]:
    """Read a quoted string starting at ``text[i] == '"'``; returns (value, next index).

    Fast path slices the whole string at once; escapes are only decoded when present."""
    j = text.find('"', i + 1)
    if j < 0:
        raise SexprError("unterminated string")
    if "\\" not in text[i + 1 : j]:
        return text[i + 1 : j], j + 1
    buf: list[str] = []
    k, n = i + 1, len(text)
    start = k
    while k < n and text[k] != '"':
        if text[k] == "\\" and k + 1 < n:
            buf.append(text[start:k])
            buf.append(_ESCAPES.get(text[k + 1], text[k + 1]))
            k += 2
            start = k
        else:
            k += 1
    if k >= n:
        raise SexprError("unterminated string")
    buf.append(text[start:k])
    return "".join(buf), k + 1


def _read_atom(text: str, i: int) -> tuple[Atom, int]:
    j, n = i, len(text)
    while j < n and text[j] not in ' \t\r\n()"':
        j += 1
    return Atom(text[i:j]), j


def parse(text: str, *, max_depth: int = MAX_DEPTH, max_tokens: int = MAX_TOKENS) -> SList:
    if len(text) > MAX_BYTES:
        raise SexprError("file too large")
    stack: list[SList] = []
    root: SList | None = None
    tokens = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        tokens += 1
        if tokens > max_tokens:
            raise SexprError("too many tokens")
        if ch == "(":
            if len(stack) >= max_depth:
                raise SexprError("nesting too deep")
            new = SList()
            if stack:
                stack[-1].append(new)
            stack.append(new)
            i += 1
        elif ch == ")":
            if not stack:
                raise SexprError(f"unbalanced ')' at offset {i}")
            done = stack.pop()
            if not stack:
                if root is not None:
                    raise SexprError("multiple top-level expressions")
                root = done
            i += 1
        else:
            item: str
            item, i = _read_string(text, i) if ch == '"' else _read_atom(text, i)
            if not stack:
                raise SexprError("value outside of list")
            stack[-1].append(item)
    if stack:
        raise SexprError("unexpected end of file (unbalanced '(')")
    if root is None:
        raise SexprError("empty document")
    return root

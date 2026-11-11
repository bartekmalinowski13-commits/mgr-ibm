"""ODB++ jobs (``.tgz`` / ``.tar.gz`` / ``.zip``) - component records of the PCB.

The archive is untrusted and never extracted to disk. It is read in memory under hard
limits (decompressed total, member count, member size) so a decompression bomb stops
early; absolute paths, ``..`` segments and links make the whole archive invalid. Only
the files the parser needs are read:

* ``<job>/steps/<step>/layers/comp_+_top|comp_+_bot/components`` - ``CMP`` records
  (package index, position, designator, part name) followed by ``PRP`` properties
  (value, MPN, manufacturer, DNP; others kept as fields);
* ``<job>/steps/<step>/eda/data`` - ``PKG`` records; ``CMP``'s package index points into
  them (package name = footprint).

Members stored with Unix ``compress`` (``.Z``) are reported, not guessed.
"""

from __future__ import annotations

import io
import posixpath
import re
import struct
import tarfile
import zipfile
import zlib
from pathlib import PurePosixPath

from bomagent_bom.dnp import parse_dnp
from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError, valid_refdes

MAX_TOTAL_BYTES = 128 * 1024 * 1024  # decompressed archive
MAX_MEMBERS = 20_000
MAX_COMPONENTS = 100_000
SNIFF_BYTES = 16 * 1024 * 1024  # decompressed prefix scanned by sniff()
SUFFIXES = (".tgz", ".tar.gz", ".zip")
_COMPONENTS = re.compile(r"^(?:.*/)?steps/([^/]+)/layers/comp_\+_(top|bot)/components(\.z)?$")
_EDA = re.compile(r"^(?:.*/)?steps/([^/]+)/eda/data$")
_PRP = re.compile(r"^PRP\s+(\S+)\s+'(.*)'\s*$")
VALUE = {"value", "val"}
MPN = {"mpn", "part_number", "manufacturer_part_number", "mfr_pn", "mpn1"}
MANUFACTURER = {"manufacturer", "mfr", "manufacturer_name", "mfr1"}
DNP = {"dnp", "no_pop", "do_not_populate", "dnf"}


#: everything the standard library raises on a corrupt archive
_ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    tarfile.TarError,
    zlib.error,
    EOFError,
    OSError,
    NotImplementedError,
    RuntimeError,
    ValueError,
    KeyError,
)


def _safe(name: str) -> str:
    path = PurePosixPath(name)
    if name.startswith(("/", "\\")) or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
        raise ParseError(f"unsafe path in archive: {name!r}", code="archive.unsafe_path")
    return posixpath.normpath(name)


def _gunzip(data: bytes, limit: int | None = None, *, strict: bool = True) -> bytes:
    """Decompress a gzip stream (all members, as pigz writes them) up to ``limit``
    bytes. ``strict``: more output than the limit is an error; else it is truncated."""
    limit = MAX_TOTAL_BYTES if limit is None else limit
    out = bytearray()
    rest = data
    while rest:
        d = zlib.decompressobj(wbits=31)
        try:
            out += d.decompress(rest, limit - len(out) + 1)
        except zlib.error as exc:
            raise ParseError("not a valid gzip stream", code="archive.malformed") from exc
        if len(out) > limit or d.unconsumed_tail:
            if strict:
                raise ParseError(
                    "archive larger than the limit when decompressed", code="archive.too_large"
                )
            return bytes(out[:limit])
        rest = d.unused_data.lstrip(b"\0")
        if rest and not rest.startswith(b"\x1f\x8b"):
            break  # trailing garbage after the last member: ignored like gzip does
    return bytes(out)


def _zip_entry_count(data: bytes) -> int:
    """Entry count from the end-of-central-directory record (zip64 too) - read before
    ``ZipFile`` builds the whole directory in memory."""
    tail = data[-(65536 + 22) :]
    at = tail.rfind(b"PK\x05\x06")
    if at < 0:
        raise ParseError("not a valid zip", code="archive.malformed")
    (count,) = struct.unpack("<H", tail[at + 10 : at + 12])
    if count == 0xFFFF:
        loc = tail.rfind(b"PK\x06\x07", 0, at)
        if loc >= 0:
            (offset,) = struct.unpack("<Q", tail[loc + 8 : loc + 16])
            record = data[offset : offset + 56]
            if record.startswith(b"PK\x06\x06"):
                (count,) = struct.unpack("<Q", record[32:40])
    return int(count)


def _tar_names(raw: bytes) -> list[str]:
    """Member names from tar headers in ``raw`` (possibly a truncated prefix)."""
    names: list[str] = []
    pos = 0
    while pos + 512 <= len(raw) and len(names) < MAX_MEMBERS:
        header = raw[pos : pos + 512]
        if header == b"\0" * 512:
            break
        name = header[0:100].split(b"\0", 1)[0]
        prefix = header[345:500].split(b"\0", 1)[0] if header[257:262] == b"ustar" else b""
        try:
            size = int(header[124:136].split(b"\0", 1)[0].strip() or b"0", 8)
        except ValueError:
            break
        full = (prefix + b"/" + name if prefix else name).decode("utf-8", "replace")
        names.append(full)
        pos += 512 + (size + 511) // 512 * 512
    return names


def read_members(file: FileRef, wanted: re.Pattern[str]) -> tuple[list[str], dict[str, bytes]]:
    """(all member names, contents of members whose name matches ``wanted``)."""
    try:
        return _read_members(file, wanted)
    except ParseError:
        raise
    except _ARCHIVE_ERRORS as exc:
        raise ParseError(
            f"{file.name}: damaged archive ({type(exc).__name__})", code="archive.malformed"
        ) from exc


def _read_members(file: FileRef, wanted: re.Pattern[str]) -> tuple[list[str], dict[str, bytes]]:
    names: list[str] = []
    out: dict[str, bytes] = {}
    if file.suffix == ".zip":
        if _zip_entry_count(file.data) > MAX_MEMBERS:
            raise ParseError(f"{file.name}: too many entries", code="archive.too_large")
        with zipfile.ZipFile(io.BytesIO(file.data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ParseError(f"{file.name}: too many entries", code="archive.too_large")
            if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
                raise ParseError(
                    f"{file.name}: larger than the limit when decompressed",
                    code="archive.too_large",
                )
            for info in infos:
                name = _safe(info.filename)
                if info.is_dir():
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink
                    raise ParseError(f"link in archive: {name!r}", code="archive.unsafe_path")
                names.append(name)
                if wanted.match(name.lower()):
                    out[name] = archive.read(info)
        return names, out
    raw = _gunzip(file.data)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for count, member in enumerate(tar):
            if count >= MAX_MEMBERS:
                raise ParseError(f"{file.name}: too many entries", code="archive.too_large")
            name = _safe(member.name)
            if member.issym() or member.islnk():
                raise ParseError(f"link in archive: {name!r}", code="archive.unsafe_path")
            if not member.isfile():
                continue
            names.append(name)
            if wanted.match(name.lower()):
                handle = tar.extractfile(member)
                if handle is not None:
                    out[name] = handle.read()
    return names, out


def _sniff_names(file: FileRef) -> list[str]:
    """Member names, cheaply: zip central directory (after an entry-count check) or tar
    headers in the first ``SNIFF_BYTES`` of the decompressed stream."""
    if file.suffix == ".zip":
        if not file.data.startswith(b"PK"):
            return []
        if _zip_entry_count(file.data) > MAX_MEMBERS:
            return []
        with zipfile.ZipFile(io.BytesIO(file.data)) as archive:
            return [i.filename for i in archive.infolist()]
    if not file.data.startswith(b"\x1f\x8b"):
        return []
    return _tar_names(_gunzip(file.data, SNIFF_BYTES, strict=False))


class OdbppParser:
    format_id = "odbpp"
    version = "1.1.0"

    def sniff(self, file: FileRef) -> float:
        if not file.name.lower().endswith(SUFFIXES):
            return 0.0
        try:
            names = _sniff_names(file)
        except (ParseError, *_ARCHIVE_ERRORS):
            return 0.0
        # an ODB++ job: claimed even if unsafe or oversized - parse() then says why
        return 0.9 if any(_COMPONENTS.match(n.lower()) for n in names) else 0.0

    def parse(self, files: list[FileRef]) -> ParsedDesign:
        candidates = [f for f in files if f.name.lower().endswith(SUFFIXES)]
        if len(candidates) != 1:
            raise ParseError("expected exactly one ODB++ archive", code="odbpp.count")
        file = candidates[0]
        pattern = re.compile(f"{_COMPONENTS.pattern}|{_EDA.pattern}")
        names, contents = read_members(file, pattern)
        layers = {n: d for n, d in contents.items() if _COMPONENTS.match(n.lower())}
        if not layers:
            raise ParseError(f"{file.name}: no component layers", code="odbpp.no_components")
        if any(n.lower().endswith(".z") for n in layers):
            raise ParseError(
                f"{file.name}: component files are compressed (.Z); export ODB++ without"
                " compression or as .tgz",
                code="odbpp.compressed_members",
            )
        steps = sorted({_COMPONENTS.match(n.lower()).group(1) for n in layers})  # type: ignore[union-attr]
        step = steps[0]
        limitations: list[str] = []
        if len(steps) > 1:
            limitations.append(f"several steps ({', '.join(steps)}); using {step!r}")
        packages: list[str] = []
        for name, data in contents.items():
            m = _EDA.match(name.lower())
            if m and m.group(1) == step:
                packages = [
                    line.split()[1]
                    for line in data.decode("utf-8", "replace").splitlines()
                    if line.startswith("PKG ") and len(line.split()) > 1
                ]
        if not packages:
            limitations.append("no eda/data package list: footprints unknown")
        components: list[Component] = []
        seen: set[str] = set()
        for name in sorted(layers):
            m = _COMPONENTS.match(name.lower())
            if m is None or m.group(1) != step:
                continue
            self._read_layer(layers[name], packages, components, seen, limitations)
            if len(components) > MAX_COMPONENTS:
                raise ParseError(f"{file.name}: too many components", code="file.too_large")
        if not components:
            raise ParseError(f"{file.name}: no component records", code="odbpp.no_components")
        job = names[0].split("/", 1)[0] if names and "/" in names[0] else file.name
        confidence = 1.0 if not limitations else max(0.6, 1.0 - 0.1 * len(limitations))
        return ParsedDesign(
            design_name=job.removesuffix(".tgz").removesuffix(".zip"),
            source_format=self.format_id,
            components=components,
            confidence=confidence,
            limitations=limitations,
            files=[f.source() for f in files],
            parser_version=self.version,
        )

    @staticmethod
    def _read_layer(
        data: bytes,
        packages: list[str],
        components: list[Component],
        seen: set[str],
        limitations: list[str],
    ) -> None:
        current: dict[str, object] | None = None

        def flush() -> None:
            if current is None:
                return
            refdes = str(current["refdes"])
            if not valid_refdes(refdes):
                limitations.append(f"{refdes!r} is not a designator - skipped")
                return
            if refdes in seen:
                limitations.append(f"{refdes} is placed more than once")
                return
            seen.add(refdes)
            components.append(
                Component(
                    refdes=refdes,
                    value=str(current["value"]),
                    footprint=str(current["footprint"]),
                    fields=dict(current["fields"]),  # type: ignore[call-overload]
                    dnp=bool(current["dnp"]),
                )
            )

        for raw_line in data.decode("utf-8", "replace").splitlines():
            line = raw_line.strip()
            if line.startswith("CMP "):
                flush()
                head = line.split(";", 1)[0].split()
                if len(head) < 7:
                    limitations.append(f"malformed component record: {line[:60]!r}")
                    current = None
                    continue
                try:
                    index = int(head[1])
                except ValueError:
                    index = -1
                footprint = packages[index] if 0 <= index < len(packages) else ""
                if packages and not footprint:
                    limitations.append(f"{head[6]}: package index {head[1]} not in eda/data")
                fields: dict[str, str] = {}
                if len(head) > 7:
                    fields["Part"] = head[7]
                current = {
                    "refdes": head[6],
                    "value": "",
                    "footprint": footprint,
                    "fields": fields,
                    "dnp": False,
                }
            elif line.startswith("PRP ") and current is not None:
                m = _PRP.match(line)
                if not m:
                    continue
                key, value = m.group(1), m.group(2)
                lowered = key.casefold()
                props: dict[str, str] = current["fields"]  # type: ignore[assignment]
                if lowered in VALUE and not current["value"]:
                    current["value"] = value
                elif lowered in MPN:
                    props.setdefault("MPN", value)
                elif lowered in MANUFACTURER:
                    props.setdefault("Manufacturer", value)
                elif lowered in DNP:
                    flag = parse_dnp(value, "dnp")
                    if flag is None:
                        limitations.append(
                            f"{current['refdes']}: DNP value {value!r} not understood - fitted"
                        )
                    current["dnp"] = bool(flag)
                else:
                    props[key] = value
        flush()

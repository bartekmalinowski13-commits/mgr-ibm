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
import tarfile
import zipfile
import zlib
from pathlib import PurePosixPath

from bomagent_bom.dnp import parse_dnp
from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError

MAX_TOTAL_BYTES = 256 * 1024 * 1024  # decompressed archive
MAX_MEMBERS = 20_000
MAX_COMPONENTS = 100_000
SUFFIXES = (".tgz", ".tar.gz", ".zip")
_COMPONENTS = re.compile(r"^(?:.*/)?steps/([^/]+)/layers/comp_\+_(top|bot)/components(\.z)?$")
_EDA = re.compile(r"^(?:.*/)?steps/([^/]+)/eda/data$")
_PRP = re.compile(r"^PRP\s+(\S+)\s+'(.*)'\s*$")
VALUE = {"value", "val"}
MPN = {"mpn", "part_number", "manufacturer_part_number", "mfr_pn", "mpn1"}
MANUFACTURER = {"manufacturer", "mfr", "manufacturer_name", "mfr1"}
DNP = {"dnp", "no_pop", "do_not_populate", "dnf"}


def _safe(name: str) -> str:
    path = PurePosixPath(name)
    if name.startswith(("/", "\\")) or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
        raise ParseError(f"unsafe path in archive: {name!r}", code="archive.unsafe_path")
    return posixpath.normpath(name)


def _gunzip(data: bytes) -> bytes:
    """Decompress a gzip stream, refusing to produce more than MAX_TOTAL_BYTES."""
    d = zlib.decompressobj(wbits=31)
    try:
        out = d.decompress(data, MAX_TOTAL_BYTES)
    except zlib.error as exc:
        raise ParseError("not a valid gzip stream", code="archive.malformed") from exc
    if d.unconsumed_tail:
        raise ParseError(
            "archive larger than the limit when decompressed", code="archive.too_large"
        )
    return out


def read_members(file: FileRef, wanted: re.Pattern[str]) -> tuple[list[str], dict[str, bytes]]:
    """(all member names, contents of members whose name matches ``wanted``)."""
    names: list[str] = []
    out: dict[str, bytes] = {}
    if file.suffix == ".zip":
        try:
            archive = zipfile.ZipFile(io.BytesIO(file.data))
        except zipfile.BadZipFile as exc:
            raise ParseError(f"{file.name}: not a valid zip", code="archive.malformed") from exc
        with archive:
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
                    out[name] = archive.read(info)[: MAX_TOTAL_BYTES + 1]
        return names, out
    raw = _gunzip(file.data)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")  # noqa: SIM115 - closed below
    except tarfile.TarError as exc:
        raise ParseError(f"{file.name}: not a valid tar archive", code="archive.malformed") from exc
    with tar:
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


class OdbppParser:
    format_id = "odbpp"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if not file.name.lower().endswith(SUFFIXES):
            return 0.0
        try:
            names, _ = read_members(file, re.compile(r"$^"))
        except ParseError as exc:
            # an unsafe or oversized archive is reported as such by parse(), not as
            # "unsupported format"; only an unreadable file is somebody else's
            return 0.0 if exc.code == "archive.malformed" else 0.6
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
                    current["dnp"] = bool(parse_dnp(value, "dnp"))
                else:
                    props[key] = value
        flush()

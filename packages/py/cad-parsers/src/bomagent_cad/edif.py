"""EDIF 2.0.0 netlists - the neutral netlist export of OrCAD Capture, Altium and others.

Read with the bounded S-expression reader (depth, token and size limits). Every
``instance`` becomes a component: the designator is the original name of a ``rename``
(EDIF identifiers cannot hold every character), the cell referenced by ``viewRef`` is
the library part, and ``property`` values map to value / footprint / MPN /
manufacturer / DNP by common property names; other properties are kept as fields.
Nets come from ``net/joined/portRef/instanceRef``. EDIF ``%nn%`` escapes are decoded.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from bomagent_bom.dnp import parse_dnp
from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError, valid_refdes
from bomagent_cad.sexpr import SexprError, SList, parse

MAX_COMPONENTS = 100_000
SUFFIXES = {".edf", ".edif", ".edn", ".edo"}
_ESCAPE = re.compile(r"%(\d{1,3})%")
VALUE = {"value", "val", "comment"}
FOOTPRINT = {"pcb_footprint", "pcb footprint", "footprint", "package", "pcb_decal", "jedec_type"}
MPN = {"mpn", "manufacturer part number", "manufacturer_part_number", "part_number", "mfr_pn"}
MANUFACTURER = {"manufacturer", "mfr", "manufacturer_name"}
DNP = {"dnp", "do_not_populate", "populate", "dnf", "no_load"}


def _decode(s: str) -> str:
    return _ESCAPE.sub(lambda m: chr(int(m.group(1))), s)


def _ident(item: object) -> tuple[str, str]:
    """(identifier, display name) of a name slot: ``R1`` or ``(rename R1 "R1")``."""
    if isinstance(item, SList) and item.head == "rename" and len(item) >= 3:
        ident = str(item[1]).lstrip("&")
        return ident, _decode(str(item[2]))
    if isinstance(item, SList) and item.head == "name" and len(item) >= 2:
        ident = str(item[1]).lstrip("&")
        return ident, ident
    ident = str(item).lstrip("&")
    return ident, ident


def _walk(node: SList, head: str) -> Iterator[SList]:
    stack = [node]
    while stack:
        cur = stack.pop()
        for item in cur[1:] if cur.head else cur:
            if isinstance(item, SList):
                if item.head == head:
                    yield item
                stack.append(item)


def _property(prop: SList) -> tuple[str, str]:
    _, name = _ident(prop[1]) if len(prop) > 1 else ("", "")
    value = ""
    for item in prop[2:]:
        if isinstance(item, SList) and item.head in {"string", "integer", "number", "boolean"}:
            raw = item[1] if len(item) > 1 else ""
            if isinstance(raw, SList) and raw.head in {"true", "false"}:
                value = raw.head
            else:
                value = _decode(str(raw))
            break
    return name, value


class EdifParser:
    format_id = "edif"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if file.suffix not in SUFFIXES:
            return 0.0
        head = file.data[:256].lstrip().lower()
        return 0.95 if head.startswith(b"(edif") else 0.0

    def parse(self, files: list[FileRef]) -> ParsedDesign:
        candidates = [f for f in files if self.sniff(f) > 0.5]
        if len(candidates) != 1:
            raise ParseError("expected exactly one EDIF netlist", code="edif.count")
        file = candidates[0]
        try:
            root = parse(file.text())
        except SexprError as exc:
            raise ParseError(f"{file.name}: invalid EDIF ({exc})", code="edif.malformed") from exc
        if root.head.lower() != "edif":
            raise ParseError(f"{file.name}: not an EDIF file", code="edif.malformed")

        limitations: list[str] = []
        components: list[Component] = []
        names: dict[str, str] = {}
        seen: set[str] = set()
        top = self._top_cell(root)
        scope = top if top is not None else root
        instances = list(_walk(scope, "instance"))
        nested = sum(1 for _ in _walk(root, "instance")) - len(instances)
        if top is None:
            limitations.append("no design statement: every instance in the file is read")
        elif nested:
            limitations.append(
                f"{nested} instances inside library or hierarchical cells are not expanded"
            )
        for inst in instances:
            if len(inst) < 2:
                continue
            ident, refdes = _ident(inst[1])
            if not valid_refdes(refdes):
                limitations.append(f"{refdes!r} is not a designator - skipped")
                continue
            if refdes in seen:
                limitations.append(f"{refdes} is instantiated more than once")
                continue
            seen.add(refdes)
            names[ident] = refdes
            cell = next(_walk(inst, "cellRef"), None)
            lib_id = _ident(cell[1])[1] if cell is not None and len(cell) > 1 else ""
            component, unknown_dnp = self._component(refdes, lib_id, inst)
            if unknown_dnp is not None:
                limitations.append(f"{refdes}: DNP value {unknown_dnp!r} not understood - fitted")
            components.append(component)
            if len(components) > MAX_COMPONENTS:
                raise ParseError(f"{file.name}: too many components", code="file.too_large")
        if not components:
            raise ParseError(f"{file.name}: no instances found", code="edif.no_components")
        if not any(c.footprint for c in components):
            limitations.append(
                "no footprint property on any instance - add PCB_FOOTPRINT to the export"
            )
        nets = self._nets(root, names)
        confidence = 1.0 if not limitations else max(0.6, 1.0 - 0.1 * len(limitations))
        design_name = _ident(root[1])[1] if len(root) > 1 else Path(file.name).stem
        return ParsedDesign(
            design_name=design_name,
            source_format=self.format_id,
            components=components,
            nets=nets or None,
            confidence=confidence,
            limitations=limitations,
            files=[f.source() for f in files],
            parser_version=self.version,
        )

    @staticmethod
    def _nets(root: SList, names: dict[str, str]) -> dict[str, list[str]]:
        """Net name -> designators, from ``net/joined/portRef/instanceRef``."""
        nets: dict[str, list[str]] = {}
        for net in _walk(root, "net"):
            if len(net) < 2:
                continue
            _, net_name = _ident(net[1])
            refs = []
            for port in _walk(net, "portRef"):
                inst_ref = next(_walk(port, "instanceRef"), None)
                if inst_ref is not None and len(inst_ref) > 1:
                    ident, _ = _ident(inst_ref[1])
                    refs.append(names.get(ident, ident))
            nets[net_name] = refs
        return nets

    @staticmethod
    def _top_cell(root: SList) -> SList | None:
        """The cell named by ``(design X (cellRef TOP (libraryRef LIB)))``."""
        design = next(root.children("design"), None)
        ref = next(_walk(design, "cellRef"), None) if design is not None else None
        if ref is None or len(ref) < 2:
            return None
        cell_name = _ident(ref[1])[0]
        lib_ref = next(ref.children("libraryRef"), None)
        lib_name = _ident(lib_ref[1])[0] if lib_ref is not None and len(lib_ref) > 1 else None
        for library in root.children("library"):
            if lib_name is not None and (len(library) < 2 or _ident(library[1])[0] != lib_name):
                continue
            for cell in library.children("cell"):
                if len(cell) > 1 and _ident(cell[1])[0] == cell_name:
                    return cell
        return None

    @staticmethod
    def _component(refdes: str, lib_id: str, inst: SList) -> tuple[Component, str | None]:
        value = footprint = ""
        dnp = False
        unknown_dnp: str | None = None
        fields: dict[str, str] = {}
        for prop in inst.children("property"):
            name, raw = _property(prop)
            key = name.casefold()
            if key in VALUE and not value:
                value = raw
            elif key in FOOTPRINT and not footprint:
                footprint = raw
            elif key in MPN:
                fields.setdefault("MPN", raw)
            elif key in MANUFACTURER:
                fields.setdefault("Manufacturer", raw)
            elif key in DNP:
                flag = parse_dnp(raw, "populate" if key == "populate" else "dnp")
                if flag is None:
                    unknown_dnp = raw
                dnp = bool(flag)
            elif name:
                fields[name] = raw
        component = Component(
            refdes=refdes,
            value=value,
            footprint=footprint,
            lib_id=lib_id,
            fields=fields,
            dnp=dnp,
        )
        return component, unknown_dnp

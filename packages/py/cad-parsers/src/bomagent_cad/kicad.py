"""KiCad 6-9 schematic (and optional PCB) parser.

Reads ``.kicad_sch`` files directly (S-expression, no KiCad installation needed):

* hierarchical sheets, including a sheet instantiated several times (each instance gets
  its own designators from the ``instances`` / ``symbol_instances`` tables);
* KiCad 6 (root ``symbol_instances``) and KiCad 7+ (per-symbol ``instances``);
* ``in_bom``, ``on_board`` and ``dnp`` flags (KiCad 6 has no DNP flag - a ``DNP`` field is
  honoured instead), all custom fields (MPN, Manufacturer, ...);
* multi-unit symbols (U1A/U1B) are merged into one component;
* optional ``.kicad_pcb``: fills missing footprints and reports mismatches.

Legacy KiCad 5 ``.sch`` files are rejected with a hint to re-save in KiCad 6+.
``kicad-cli sch export bom`` can be used as an independent cross-check (FORMATS.md) but is
not required at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from bomagent_bom.model import Component, ParsedDesign
from bomagent_bom.refdes import natural_key
from bomagent_cad.base import FileRef, ParseError
from bomagent_cad.sexpr import SexprError, SList, parse

MIN_VERSION = 20211014  # KiCad 6.0
KICAD_MAJOR = ((20250000, 9), (20231000, 8), (20221000, 7), (20211014, 6))
TRUTHY = {"yes", "true", "1"}
# budgets against hostile hierarchies (a sheet listed twice in itself fans out 2^depth)
MAX_SHEET_INSTANCES = 1_000
MAX_COMPONENTS = 100_000
DNP_VALUES = {"dnp", "dnf", "nf", "no fit", "do not populate", "yes", "true", "1"}


def kicad_major(version: int) -> int:
    return next(major for floor, major in KICAD_MAJOR if version >= floor)


@dataclass
class _Sheet:
    file: FileRef
    tree: SList
    version: int


@dataclass
class _Ctx:
    sheets: dict[str, _Sheet]
    root_uuid: str
    root_symbol_instances: dict[str, dict[str, str]]
    components: dict[str, Component] = field(default_factory=dict)
    sheet_paths: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    instance_fallbacks: int = 0
    unannotated: list[str] = field(default_factory=list)
    project: str = ""
    stack: list[str] = field(default_factory=list)
    sheet_instances: int = 0
    duplicates: list[Component] = field(default_factory=list)
    foreign_projects: set[str] = field(default_factory=set)
    units: dict[str, set[str]] = field(default_factory=dict)


def _props(sym: SList) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sym.children("property"):
        if len(p) >= 3 and isinstance(p[1], str) and isinstance(p[2], str):
            out[str(p[1])] = str(p[2])
    return out


def _flag(sym: SList, name: str, default: bool) -> bool:
    raw = sym.value(name, "")
    return raw.lower() in TRUTHY if raw else default


def _load(file: FileRef) -> _Sheet:
    try:
        tree = parse(file.text())
    except SexprError as exc:
        raise ParseError(
            f"{file.name}: malformed KiCad file ({exc})", code="kicad.malformed"
        ) from exc
    if tree.head != "kicad_sch":
        raise ParseError(f"{file.name}: not a KiCad schematic", code="kicad.not_schematic")
    try:
        version = int(tree.value("version", "0"))
    except ValueError as exc:
        raise ParseError(f"{file.name}: invalid version", code="kicad.malformed") from exc
    if version < MIN_VERSION:
        raise ParseError(
            f"{file.name}: KiCad 5 or older format - open and save it in KiCad 6+",
            code="kicad.legacy",
        )
    return _Sheet(file, tree, version)


class KicadParser:
    format_id = "kicad"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if file.suffix == ".kicad_sch":
            return 1.0 if file.data.lstrip()[:12].startswith(b"(kicad_sch") else 0.3
        if file.suffix in {".kicad_pcb", ".kicad_pro"}:
            return 0.5
        if file.suffix == ".sch" and file.data.startswith(b"EESchema"):
            return 0.9  # legacy KiCad 5 - parse() explains how to convert
        return 0.0

    # ------------------------------------------------------------------ public
    def parse(self, files: list[FileRef]) -> ParsedDesign:
        legacy = [f for f in files if f.suffix == ".sch" and f.data.startswith(b"EESchema")]
        if legacy:
            raise ParseError(
                f"{legacy[0].name}: KiCad 5 legacy schematic - open and save it in KiCad 6+",
                code="kicad.legacy",
            )
        schematics = {f.name: f for f in files if f.suffix == ".kicad_sch"}
        if not schematics:
            raise ParseError("no .kicad_sch file in the upload", code="kicad.no_schematic")
        sheets = {name: _load(f) for name, f in schematics.items()}
        root_name = self._root(sheets, files)
        root = sheets[root_name]
        pro = next((f for f in files if f.suffix == ".kicad_pro"), None)
        ctx = _Ctx(
            sheets=sheets,
            root_uuid=root.tree.value("uuid"),
            root_symbol_instances=self._legacy_instances(root.tree),
            project=PurePosixPath(pro.name if pro else root_name).stem,
        )
        self._walk(ctx, root_name, f"/{ctx.root_uuid}", "/", depth=0)
        if ctx.instance_fallbacks:
            ctx.limitations.append(
                f"{ctx.instance_fallbacks} symbol(s) had no instance data; "
                "designators were taken from the Reference field"
            )
        if ctx.foreign_projects:
            ctx.limitations.append(
                "instance data of other project(s) ignored: "
                + ", ".join(sorted(ctx.foreign_projects)[:5])
            )
        if ctx.duplicates:
            ctx.limitations.append(
                "duplicate designators used by different symbols: "
                + ", ".join(sorted({c.refdes for c in ctx.duplicates})[:20])
            )
        pcb = next((f for f in files if f.suffix == ".kicad_pcb"), None)
        if pcb is not None:
            self._merge_pcb(ctx, pcb)
        else:
            ctx.limitations.append(
                "no .kicad_pcb provided: footprints come from the schematic only"
            )
        comps = sorted(
            [*ctx.components.values(), *ctx.duplicates], key=lambda c: natural_key(c.refdes)
        )
        unannotated = ctx.unannotated
        if unannotated:
            ctx.limitations.append(
                f"{len(unannotated)} unannotated symbol(s) skipped "
                f"({', '.join(unannotated[:10])}) - annotate the schematic in KiCad"
            )
        missing_sheets = sum("sheet file not provided" in m for m in ctx.limitations)
        confidence = max(
            0.3,
            1.0
            - 0.25 * missing_sheets
            - (0.1 if unannotated else 0.0)
            - (0.2 if ctx.instance_fallbacks else 0.0)
            - (0.2 if ctx.duplicates else 0.0),
        )
        design = PurePosixPath(root_name).stem
        return ParsedDesign(
            design_name=design,
            source_format=f"kicad{kicad_major(root.version)}",
            components=comps,
            sheets=ctx.sheet_paths,
            confidence=confidence,
            limitations=ctx.limitations,
            files=[f.source() for f in files],
            parser_version=self.version,
        )

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _root(sheets: dict[str, _Sheet], files: list[FileRef]) -> str:
        pro = next((f for f in files if f.suffix == ".kicad_pro"), None)
        if pro is not None:
            candidate = PurePosixPath(pro.name).stem + ".kicad_sch"
            if candidate in sheets:
                return candidate
        referenced = {
            PurePosixPath(_props(s).get("Sheetfile", _props(s).get("Sheet file", ""))).name
            for sh in sheets.values()
            for s in sh.tree.children("sheet")
        }
        roots = [name for name in sheets if name not in referenced]
        if len(roots) != 1:
            raise ParseError(
                "cannot determine the root schematic - include the .kicad_pro file",
                code="kicad.ambiguous_root",
            )
        return roots[0]

    @staticmethod
    def _legacy_instances(root: SList) -> dict[str, dict[str, str]]:
        """KiCad 6: ``(symbol_instances (path "/a/b" (reference "R1") (unit 1) ...))``."""
        table: dict[str, dict[str, str]] = {}
        block = root.child("symbol_instances")
        if block is None:
            return table
        for path in block.children("path"):
            table[str(path[1])] = {
                "reference": path.value("reference"),
                "value": path.value("value"),
                "footprint": path.value("footprint"),
            }
        return table

    def _walk(self, ctx: _Ctx, name: str, path: str, sheet_path: str, depth: int) -> None:
        if depth > 32 or name in ctx.stack:
            raise ParseError(
                "recursive or too deep sheet hierarchy (a sheet contains itself?)",
                code="kicad.recursion",
            )
        ctx.sheet_instances += 1
        if ctx.sheet_instances > MAX_SHEET_INSTANCES or len(ctx.components) > MAX_COMPONENTS:
            raise ParseError(
                "design too large or hierarchy fans out too much", code="kicad.too_complex"
            )
        ctx.stack.append(name)
        sheet = ctx.sheets[name]
        ctx.sheet_paths.append(sheet_path)
        for sym in sheet.tree.children("symbol"):
            self._add_symbol(ctx, sym, path, sheet_path)
        for sub in sheet.tree.children("sheet"):
            props = _props(sub)
            # uploads are flat: "sub/ch.kicad_sch" is matched by its file name
            file_name = PurePosixPath(props.get("Sheetfile", props.get("Sheet file", ""))).name
            sheet_name = props.get("Sheetname", props.get("Sheet name", file_name))
            child_path = f"{path}/{sub.value('uuid')}"
            if file_name not in ctx.sheets:
                ctx.limitations.append(f"sheet file not provided: {file_name}")
                continue
            self._walk(
                ctx, file_name, child_path, f"{sheet_path.rstrip('/')}/{sheet_name}", depth + 1
            )
        ctx.stack.pop()

    def _reference(self, ctx: _Ctx, sym: SList, path: str) -> list[tuple[str, dict[str, str]]]:
        """Designators of this symbol at ``path`` with per-instance overrides
        (KiCad 6 stores value/footprint per instance)."""
        instances = sym.child("instances")
        if instances is not None:
            by_project: dict[str, list[str]] = {}
            for project in instances.children("project"):
                name = str(project[1]) if len(project) > 1 else ""
                by_project.setdefault(name, []).extend(
                    p.value("reference") for p in project.children("path") if str(p[1]) == path
                )
            refs = by_project.get(ctx.project)
            if refs:
                ctx.foreign_projects.update(n for n in by_project if n != ctx.project)
                return [(r, {}) for r in refs]
            others = [r for refs_ in by_project.values() for r in refs_]
            if others:
                if len(by_project) > 1:
                    ctx.foreign_projects.update(by_project)
                return [(r, {}) for r in dict.fromkeys(others)]
        # KiCad 6: root table keyed by path without root uuid + symbol uuid
        legacy_path = path.removeprefix(f"/{ctx.root_uuid}") + f"/{sym.value('uuid')}"
        entry = ctx.root_symbol_instances.get(legacy_path)
        if entry and entry["reference"]:
            overrides = {k: entry[k] for k in ("value", "footprint") if entry.get(k)}
            return [(entry["reference"], overrides)]
        ctx.instance_fallbacks += 1
        return [(_props(sym).get("Reference", ""), {})]

    def _add_symbol(self, ctx: _Ctx, sym: SList, path: str, sheet_path: str) -> None:
        lib_id = sym.value("lib_id")
        props = _props(sym)
        is_power = lib_id.startswith("power:") or props.get("Reference", "").startswith("#")
        if is_power:
            return
        fields = {
            k: v
            for k, v in props.items()
            if k not in {"Reference", "Value", "Footprint"} and v not in {"", "~"}
        }
        dnp_field = fields.get("DNP", "").strip().lower()
        dnp = _flag(sym, "dnp", False) or dnp_field in DNP_VALUES
        unit = sym.value("unit", "1")
        for ref, overrides in self._reference(ctx, sym, path):
            if not ref or ref.startswith("#"):
                continue
            if ref.endswith("?"):
                ctx.unannotated.append(ref)
                continue
            existing = ctx.components.get(ref)
            if existing is not None:
                if existing.lib_id == lib_id and unit not in ctx.units.get(ref, set()):
                    ctx.units.setdefault(ref, set()).add(unit)
                    # another unit of the same multi-unit symbol
                    merged = {**fields, **existing.fields}
                    ctx.components[ref] = existing.model_copy(update={"fields": merged})
                    continue
                # a *different* symbol re-using the designator: keep both so that the
                # rule refdes.unique reports it instead of silently merging
                ctx.duplicates.append(
                    existing.model_copy(
                        update={
                            "value": overrides.get("value", props.get("Value", "")),
                            "footprint": overrides.get("footprint", props.get("Footprint", "")),
                            "lib_id": lib_id,
                            "fields": fields,
                            "dnp": dnp,
                            "sheet_path": sheet_path,
                        }
                    )
                )
                continue
            try:
                ctx.components[ref] = Component(
                    refdes=ref,
                    value=overrides.get("value", props.get("Value", "")),
                    footprint=overrides.get("footprint", props.get("Footprint", "")),
                    lib_id=lib_id,
                    fields=fields,
                    dnp=dnp,
                    in_bom=_flag(sym, "in_bom", True),
                    sheet_path=sheet_path,
                )
            except ValueError:
                ctx.limitations.append(f"invalid designator {ref!r} skipped")
                continue
            ctx.units[ref] = {unit}

    @staticmethod
    def _merge_pcb(ctx: _Ctx, pcb: FileRef) -> None:
        try:
            tree = parse(pcb.text())
        except SexprError as exc:
            ctx.limitations.append(f"{pcb.name}: PCB file could not be read ({exc})")
            return
        if tree.head != "kicad_pcb":
            ctx.limitations.append(f"{pcb.name}: not a KiCad PCB file")
            return
        mismatches: list[str] = []
        for fp in tree.children("footprint"):
            lib = str(fp[1]) if len(fp) > 1 and isinstance(fp[1], str) else ""
            ref = _props(fp).get("Reference", "")
            if not ref:  # KiCad 6/7: (fp_text reference "R1" ...)
                for t in fp.children("fp_text"):
                    if len(t) > 2 and str(t[1]) == "reference":
                        ref = str(t[2])
            comp = ctx.components.get(ref)
            if comp is None:
                continue
            if not comp.footprint and lib:
                ctx.components[ref] = comp.model_copy(update={"footprint": lib})
            elif lib and comp.footprint != lib:
                mismatches.append(ref)
        if mismatches:
            ctx.limitations.append(
                "schematic and PCB footprints differ for: " + ", ".join(sorted(mismatches)[:20])
            )

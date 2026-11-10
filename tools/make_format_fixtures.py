"""Generate IPC-2581, EDIF and ODB++ fixtures from the open KiCad fixtures (M7).

The generated files describe exactly the same parts as the KiCad designs, so each new
parser gets a cross-format consistency test against the KiCad parse. They mimic what
EDA tools export (IPC-2581 rev C with BOM + AVL, EDIF 2.0.0 netlist with properties);
they are self-authored and carry the licence of the KiCad fixtures (evals/fixtures/SOURCES.md).

    PYTHONHASHSEED=0 uv run python tools/make_format_fixtures.py   # byte-identical DXF
"""

from __future__ import annotations

import gzip
import io
import tarfile
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import quoteattr

from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad import FileRef, parse_files

ROOT = Path(__file__).resolve().parents[1]
KICAD = ROOT / "evals" / "fixtures" / "kicad"
DESIGNS = ("ecg-frontend", "pulse-ox", "eeg-2ch")


def kicad_design(name: str) -> ParsedDesign:
    files = [
        FileRef.from_path(p)
        for p in sorted((KICAD / name).iterdir())
        if p.suffix.startswith(".kicad")
    ]
    return parse_files(files)


def _package(c: Component) -> str:
    return c.footprint.split(":")[-1]


def ipc2581(design: ParsedDesign) -> str:
    parts = design.bom_components()
    groups: dict[tuple[str, str, str, str], list[Component]] = defaultdict(list)
    for c in parts:
        groups[(c.value, _package(c), c.field("MPN"), c.field("Manufacturer"))].append(c)
    vendors = sorted({k[3] for k in groups if k[3]})
    q = quoteattr
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<IPC-2581 revision="C" xmlns="http://webstds.ipc.org/2581">',
        f'  <Content roleRef="Owner"><FunctionMode mode="ASSEMBLY"/>'
        f"<StepRef name={q(design.design_name)}/><BomRef name={q(design.design_name + '_BOM')}/>"
        "</Content>",
        "  <LogisticHeader>",
        '    <Role id="Owner" roleFunction="SENDER"/>',
        *(
            f'    <Enterprise id={q("V" + str(i))} name={q(v)} code="NONE"/>'
            for i, v in enumerate(vendors)
        ),
        "  </LogisticHeader>",
        f"  <Bom name={q(design.design_name + '_BOM')}>",
        f'    <BomHeader assembly={q(design.design_name)} revision="1"/>',
    ]
    for n, ((value, package, _mpn, _mfr), comps) in enumerate(sorted(groups.items())):
        out.append(
            f'    <BomItem OEMDesignNumberRef="ITEM-{n + 1}" quantity="{len(comps)}"'
            f' category="ELECTRICAL" description={q(comps[0].field("Description"))}>'
        )
        for c in sorted(comps, key=lambda c: c.refdes):
            populate = "false" if c.dnp else "true"
            out.append(
                f"      <RefDes name={q(c.refdes)} packageRef={q(package)}"
                f' populate="{populate}" layerRef="TOP"/>'
            )
        out.append(
            '      <Characteristics category="ELECTRICAL">'
            f'<Textual definitionSource="VALUE" textualCharacteristicName="Value"'
            f" textualCharacteristicValue={q(value)}/></Characteristics>"
        )
        out.append("    </BomItem>")
    out.append("  </Bom>")
    out.append('  <Ecad name="design"><CadData><Step name=' + q(design.design_name) + ">")
    for c in sorted(parts, key=lambda c: c.refdes):
        out.append(
            f"    <Component refDes={q(c.refdes)} packageRef={q(_package(c))}"
            f' layerRef="TOP" part={q(c.value)}/>'
        )
    out.append("  </Step></CadData></Ecad>")
    out.append('  <Avl name="AVL">')
    for n, ((_v, _p, mpn, mfr), _c) in enumerate(sorted(groups.items())):
        if not mpn:
            continue
        vendor = f"V{vendors.index(mfr)}" if mfr else ""
        out.append(f'    <AvlItem OEMDesignNumber="ITEM-{n + 1}">')
        out.append(
            f'      <AvlVmpn qualified="true" chosen="true"><AvlMpn name={q(mpn)} rank="1"/>'
            + (f"<AvlVendor enterpriseRef={q(vendor)}/>" if vendor else "")
            + "</AvlVmpn>"
        )
        out.append("    </AvlItem>")
    out.append("  </Avl>")
    out.append("</IPC-2581>")
    return "\n".join(out) + "\n"


def _edif_str(s: str) -> str:
    return '"' + s.replace("%", "%37%").replace('"', "%34%") + '"'


def edif(design: ParsedDesign) -> str:
    parts = sorted(design.bom_components(), key=lambda c: c.refdes)
    cells = sorted({c.lib_id.split(":")[-1] or "PART" for c in parts})
    lines = [
        f"(edif {_ident(design.design_name)}",
        "  (edifVersion 2 0 0)",
        "  (edifLevel 0)",
        "  (keywordMap (keywordLevel 0))",
        '  (status (written (timeStamp 2026 11 10 12 0 0) (program "bomagent fixtures")))',
        "  (library parts (edifLevel 0) (technology (numberDefinition))",
    ]
    for cell in cells:
        lines += [
            f"    (cell {_ident(cell)} (cellType GENERIC)",
            "      (view netlist (viewType NETLIST)",
            "        (interface (port 1 (direction INOUT)) (port 2 (direction INOUT)))))",
        ]
    lines += [
        "  )",
        "  (library design (edifLevel 0) (technology (numberDefinition))",
        f"    (cell {_ident(design.design_name)} (cellType GENERIC)",
        "      (view netlist (viewType NETLIST)",
        "        (interface)",
        "        (contents",
    ]
    for c in parts:
        props = [("VALUE", c.value), ("PCB_FOOTPRINT", c.footprint)]
        props += [("MPN", c.field("MPN")), ("MANUFACTURER", c.field("Manufacturer"))]
        if c.dnp:
            props.append(("DNP", "1"))
        lines.append(
            f"          (instance (rename {_ident(c.refdes)} {_edif_str(c.refdes)})"
            f" (viewRef netlist (cellRef {_ident(c.lib_id.split(':')[-1] or 'PART')}"
            " (libraryRef parts)))"
        )
        for key, value in props:
            if value:
                lines.append(f"            (property {key} (string {_edif_str(value)}))")
        lines.append("          )")
    # one illustrative net: pin 1 of the first two parts
    if len(parts) >= 2:
        a, b = parts[0], parts[1]
        lines.append(
            f"          (net GND (joined (portRef 1 (instanceRef {_ident(a.refdes)}))"
            f" (portRef 1 (instanceRef {_ident(b.refdes)}))))"
        )
    lines += [
        "        ))))",
        f"  (design {_ident(design.design_name)}"
        f" (cellRef {_ident(design.design_name)} (libraryRef design))))",
        "",
    ]
    return "\n".join(lines)


def _ident(s: str) -> str:
    """EDIF identifiers: letters, digits, underscore; must start with a letter (&-escaped)."""
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in s)
    return cleaned if cleaned[:1].isalpha() else "&" + cleaned


def odbpp(design: ParsedDesign) -> bytes:
    """ODB++ job as .tgz: eda/data (packages) + comp_+_top/components (CMP/PRP records)."""
    parts = sorted(design.bom_components(), key=lambda c: c.refdes)
    packages = sorted({_package(c) for c in parts})
    job = design.design_name
    eda = ["# ODB++ eda data (fixture)", "HDR bomagent fixtures"]
    eda += [f"PKG {p} 1.27 -1 -1 1 1" for p in packages]
    comps = ["# component records", "UNITS=MM"]
    for i, c in enumerate(parts):
        comps.append(f"# CMP {i}")
        part = c.field("MPN") or c.value
        comps.append(f"CMP {packages.index(_package(c))} 10.0 {i * 2.5:.1f} 0 N {c.refdes} {part}")
        props = [
            ("VALUE", c.value),
            ("MPN", c.field("MPN")),
            ("MANUFACTURER", c.field("Manufacturer")),
        ]
        if c.dnp:
            props.append(("DNP", "YES"))
        comps += [f"PRP {k} '{v}'" for k, v in props if v]
    files = {
        f"{job}/matrix/matrix": "STEP {\n   COL=1\n   NAME=PCB\n}\n",
        f"{job}/steps/pcb/eda/data": "\n".join(eda) + "\n",
        f"{job}/steps/pcb/layers/comp_+_top/components": "\n".join(comps) + "\n",
    }
    buf = io.BytesIO()
    # deterministic archive: fixed mtime, sorted members, no owner names
    with (
        gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for path, text in sorted(files.items()):
            data = text.encode()
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


#: mechanical parts list of the ECG front-end enclosure (self-authored example)
MECHANICAL = [
    # pos, part number, description, qty, material, manufacturer
    ("1", "1551KTBU", "Enclosure, top and bottom shell", "1", "ABS UL94-HB", "Hammond"),
    ("2", "ISO7380-M2x6-A2", "Button head screw M2x6", "4", "Stainless A2", ""),
    ("3", "LP-3MM-12", "Light pipe 3 mm", "1", "PC", "Bivar"),
    ("4", "GSK-ECG-01", "Gasket, front panel", "1", "Silicone 40 ShA", ""),
    ("5", "LBL-ECG-01", "Product label (applied part BF symbol)", "1", "Polyester", ""),
]
DXF_HEADERS = ("POS", "PART NUMBER", "DESCRIPTION", "QTY", "MATERIAL", "MANUFACTURER")


def dxf_attribs() -> str:
    """Parts list as blocks with attributes (one INSERT per row)."""
    import ezdxf

    doc = ezdxf.new("R2010")
    block = doc.blocks.new("BOM_ROW")
    tags = ("POS", "PART_NO", "DESCRIPTION", "QTY", "MATERIAL", "MANUFACTURER")
    for i, tag in enumerate(tags):
        block.add_attdef(tag, (i * 30, 0), dxfattribs={"height": 2.5})
    msp = doc.modelspace()
    for row, values in enumerate(MECHANICAL):
        insert = msp.add_blockref("BOM_ROW", (0, row * 5))
        insert.add_auto_attribs(dict(zip(tags, values, strict=True)))
    return _dxf_text(doc)


def dxf_table() -> str:
    """Parts list as a grid of TEXT entities (exploded table), header at the bottom
    and rows stacked upwards, as in ISO 7573 parts lists."""
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    columns = (0, 15, 60, 130, 145, 185)
    for x, header in zip(columns, DXF_HEADERS, strict=True):
        msp.add_text(header, height=2.5, dxfattribs={"insert": (x, 0)})
    for row, values in enumerate(MECHANICAL, start=1):
        for x, value in zip(columns, values, strict=True):
            if value:
                msp.add_text(value, height=2.5, dxfattribs={"insert": (x, row * 6)})
    msp.add_text("Title: ECG front-end enclosure", height=5, dxfattribs={"insert": (0, -30)})
    return _dxf_text(doc)


def _dxf_text(doc: object) -> str:
    stream = io.StringIO()
    doc.write(stream)  # type: ignore[attr-defined]
    # drop volatile header values (timestamps, GUIDs) so the fixture is reproducible
    lines = stream.getvalue().splitlines()
    out: list[str] = []
    skip = 0
    for i, line in enumerate(lines):
        if skip:
            skip -= 1
            continue
        if line.strip() in {
            "$TDCREATE",
            "$TDUPDATE",
            "$TDUCREATE",
            "$TDUUPDATE",
            "$FINGERPRINTGUID",
            "$VERSIONGUID",
            "$TDINDWG",
        }:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            skip = 2 if nxt in {"40", "2"} else 0
            if skip:
                out.append(line)
                out.append(lines[i + 1])
                out.append("0" if nxt == "40" else "{00000000-0000-0000-0000-000000000000}")
            continue
        out.append(line)
    return "\n".join(out) + "\n"


PDF_COLUMNS = (
    ("Designator", 40),
    ("Qty", 150),
    ("Value", 180),
    ("Footprint", 230),
    ("Manufacturer", 410),
    ("MPN", 520),
    ("DNP", 640),
)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_bom(reference_csv: Path, title: str) -> bytes:
    """A one-table PDF BOM (Helvetica text, landscape A4) as BOM exports print it."""
    import csv

    rows = list(csv.DictReader(reference_csv.open(encoding="utf-8")))
    ops = ["BT /F1 12 Tf 40 560 Td (" + _pdf_escape(f"Bill of materials - {title}") + ") Tj ET"]
    y = 530
    for header, x in PDF_COLUMNS:
        ops.append(f"BT /F2 8 Tf {x} {y} Td ({header}) Tj ET")
    for row in rows:
        y -= 14
        cells = {
            "Designator": row["Reference"].replace(" ", ", "),
            "Qty": row["Qty"],
            "Value": row["Value"],
            "Footprint": row["Footprint"].split(":")[-1],
            "Manufacturer": row["Manufacturer"],
            "MPN": row["MPN"],
            "DNP": "DNP" if row["DNP"].strip() else "",
        }
        for header, x in PDF_COLUMNS:
            if cells[header]:
                ops.append(f"BT /F1 8 Tf {x} {y} Td ({_pdf_escape(cells[header])}) Tj ET")
    content = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def main() -> None:
    for name in DESIGNS:
        design = kicad_design(name)
        for fmt, ext, render in (("ipc2581", "xml", ipc2581), ("edif", "edf", edif)):
            target = ROOT / "evals" / "fixtures" / fmt / f"{name}.{ext}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render(design), encoding="utf-8")
            print(target.relative_to(ROOT))
        target = ROOT / "evals" / "fixtures" / "odbpp" / f"{name}.tgz"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(odbpp(design))
        print(target.relative_to(ROOT))
    for name in DESIGNS:
        target = ROOT / "evals" / "fixtures" / "pdf-bom" / f"{name}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf_bom(KICAD / name / "reference_bom.csv", name))
        print(target.relative_to(ROOT))
    for name, render_dxf in (("enclosure-attribs", dxf_attribs), ("enclosure-table", dxf_table)):
        target = ROOT / "evals" / "fixtures" / "dxf" / f"{name}.dxf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_dxf(), encoding="utf-8")
        print(target.relative_to(ROOT))


if __name__ == "__main__":
    main()

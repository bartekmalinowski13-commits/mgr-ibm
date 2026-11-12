"""Generate self-authored KiCad fixture projects (CC0-1.0) and their reference BOMs.

Usage:  uv run python tools/fixtures/gen_kicad_fixtures.py evals/fixtures/kicad

The projects are small but structurally realistic biomedical front-ends exercising the
parser paths that matter: KiCad 6 (root ``symbol_instances``), KiCad 8 (hierarchical
sheets), KiCad 9 (one sheet instantiated twice, multi-unit op-amp), DNP flag vs DNP field,
power symbols, ``in_bom no`` parts, parts without MPN (to be completed by agents/rules).

The reference BOM (``reference_bom.csv``) is the human "truth" for evaluation: it contains
MPNs also for parts whose schematic symbol has none, plus acceptable alternates.
Part numbers are real catalogue parts used as test data; electrical correctness of the
circuits is not the goal.
"""

from __future__ import annotations

import csv
import json
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

NS = uuid.UUID("6f0c2f9e-3a52-4e0b-9a63-0d9c2b1c7e11")


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Part:
    ref: str  # designator in the first (or only) instance
    lib_id: str
    value: str
    footprint: str
    mpn: str = ""  # MPN written in the schematic (may be empty)
    manufacturer: str = ""
    ref_mpn: str = ""  # MPN in the reference BOM (defaults to mpn)
    ref_manufacturer: str = ""
    alternates: str = ""  # acceptable alternative MPNs (space separated)
    description: str = ""
    dnp: bool = False
    dnp_as_field: bool = False  # KiCad 6 style
    in_bom: bool = True
    units: int = 1
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Sheet:
    file: str
    parts: list[Part]
    children: list[tuple[str, str]] = field(default_factory=list)  # (sheet name, file)


@dataclass
class Project:
    name: str
    version: int
    generator_version: str
    sheets: dict[str, Sheet]
    root: str
    # per sheet-instance designator remapping: instance name -> {ref: new_ref}
    instance_refs: dict[str, dict[str, str]] = field(default_factory=dict)
    power: tuple[str, ...] = ("GND", "+3V3")


def symbol_block(
    p: Part, sym_uuid: str, instances: list[tuple[str, str, str]], v6: bool, unit: int, x: float
) -> str:
    """instances: (project, path, reference)."""
    props = [
        ("Reference", p.ref),
        ("Value", p.value),
        ("Footprint", p.footprint),
        ("Datasheet", "~"),
    ]
    if p.mpn:
        props.append(("MPN", p.mpn))
    if p.manufacturer:
        props.append(("Manufacturer", p.manufacturer))
    if p.description:
        props.append(("Description", p.description))
    if p.dnp_as_field:
        props.append(("DNP", "DNP"))
    props.extend(p.extra.items())
    lines = [
        "  (symbol",
        f"    (lib_id {q(p.lib_id)})",
        f"    (at {x:.2f} 50.8 0)",
        f"    (unit {unit})",
    ]
    if not v6:
        lines.append("    (exclude_from_sim no)")
    lines.append(f"    (in_bom {'yes' if p.in_bom else 'no'})")
    lines.append("    (on_board yes)")
    if not v6:
        lines.append(f"    (dnp {'yes' if p.dnp else 'no'})")
    lines.append(f"    (uuid {q(sym_uuid)})")
    for i, (k, v) in enumerate(props):
        idx = f" (id {i})" if v6 else ""
        lines.append(f"    (property {q(k)} {q(v)}{idx} (at {x:.2f} 48.26 0)")
        lines.append("      (effects (font (size 1.27 1.27)) (hide yes))")
        lines.append("    )")
    lines.append(f'    (pin "1" (uuid {q(uid(sym_uuid, "pin1"))}))')
    if not v6:
        lines.append("    (instances")
        by_project: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for proj, path, ref in instances:
            by_project[proj].append((path, ref))
        for proj, entries in by_project.items():
            lines.append(f"      (project {q(proj)}")
            for path, ref in entries:
                lines.append(f"        (path {q(path)} (reference {q(ref)}) (unit {unit}))")
            lines.append("      )")
        lines.append("    )")
    lines.append("  )")
    return "\n".join(lines)


def power_block(name: str, idx: int, sheet_uuid_path: str, project: str, v6: bool) -> str:
    sym_uuid = uid(project, sheet_uuid_path, "pwr", name, str(idx))
    ref = f"#PWR0{idx:02d}"
    p = Part(ref=ref, lib_id=f"power:{name}", value=name, footprint="")
    return symbol_block(p, sym_uuid, [(project, sheet_uuid_path, ref)], v6, 1, 10.0 + idx)


def render(project: Project, out: Path) -> dict[str, list[str]]:
    """Write the schematic files; returns refdes per sheet instance path for checks."""
    v6 = project.version < 20220000
    root_uuid = uid(project.name, "root")
    sheet_uuids: dict[tuple[str, str], str] = {}
    # instance paths of each sheet file: list of (uuid path, instance name)
    paths: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def visit(file: str, path: str, inst: str) -> None:
        paths[file].append((path, inst))
        for name, child in project.sheets[file].children:
            su = sheet_uuids.setdefault((file, name), uid(project.name, file, name))
            visit(child, f"{path}/{su}", name)

    visit(project.root, f"/{root_uuid}", "root")
    legacy_instances: list[str] = []
    for file, sheet in project.sheets.items():
        blocks: list[str] = []
        x = 20.0
        for part in sheet.parts:
            for unit in range(1, part.units + 1):
                sym_uuid = uid(project.name, file, part.ref, str(unit))
                instances = []
                for path, inst in paths[file]:
                    ref = project.instance_refs.get(inst, {}).get(part.ref, part.ref)
                    instances.append((project.name, path, ref))
                    if v6:
                        legacy_path = path.removeprefix(f"/{root_uuid}") + f"/{sym_uuid}"
                        legacy_instances.append(
                            f"    (path {q(legacy_path)}\n      (reference {q(ref)}) (unit {unit})"
                            f" (value {q(part.value)}) (footprint {q(part.footprint)})\n    )"
                        )
                blocks.append(symbol_block(part, sym_uuid, instances, v6, unit, x))
                x += 7.62
        for i, pwr in enumerate(project.power, start=1):
            if file == project.root or i == 1:
                blocks.append(
                    power_block(pwr, i + 10 * len(blocks), paths[file][0][0], project.name, v6)
                )
        for name, child in sheet.children:
            su = sheet_uuids[(file, name)]
            sheet_lines = [
                "  (sheet (at 150 50) (size 30 20)",
                f"    (uuid {q(su)})",
                f'    (property "Sheetname" {q(name)}{" (id 0)" if v6 else ""} (at 150 49 0)'
                " (effects (font (size 1.27 1.27))))",
                f'    (property "Sheetfile" {q(child)}{" (id 1)" if v6 else ""} (at 150 71 0)'
                " (effects (font (size 1.27 1.27))))",
            ]
            if not v6:
                sheet_lines.append(
                    f"    (instances (project {q(project.name)} (path {q(paths[file][0][0])}"
                    f" (page {q(str(len(sheet_lines)))}))))"
                )
            sheet_lines.append("  )")
            blocks.append("\n".join(sheet_lines))
        header = [
            "(kicad_sch",
            f"  (version {project.version})",
            '  (generator "eeschema")',
        ]
        if not v6:
            header.append(f"  (generator_version {q(project.generator_version)})")
        file_uuid = root_uuid if file == project.root else uid(project.name, "file", file)
        header += [f"  (uuid {q(file_uuid)})", '  (paper "A4")', "  (lib_symbols)"]
        body = "\n".join(header + blocks)
        if file == project.root:
            body += '\n  (sheet_instances (path "/" (page "1")))'
            if v6:
                body += "\n  (symbol_instances\n" + "\n".join(legacy_instances) + "\n  )"
        (out / file).write_text(body + "\n)\n", encoding="utf-8")
    (out / f"{project.name}.kicad_pro").write_text(
        json.dumps({"meta": {"filename": f"{project.name}.kicad_pro", "version": 1}}, indent=2)
        + "\n"
    )
    return {}


def reference_bom(project: Project, out: Path) -> None:
    """Write the reference BOM (grouped lines) and the flat expected component list."""
    v_rows: dict[tuple[str, ...], list[str]] = defaultdict(list)
    meta: dict[tuple[str, ...], Part] = {}
    alternates: dict[tuple[str, ...], set[str]] = defaultdict(set)
    flat: list[dict[str, object]] = []

    def instances_of(file: str) -> list[str]:
        names: list[str] = []

        def walk(f: str, inst: str) -> None:
            if f == file:
                names.append(inst)
            for n, child in project.sheets[f].children:
                walk(child, n)

        walk(project.root, "root")
        return names

    for file, sheet in project.sheets.items():
        for inst in instances_of(file):
            for part in sheet.parts:
                if not part.in_bom:
                    continue
                ref = project.instance_refs.get(inst, {}).get(part.ref, part.ref)
                mpn = part.ref_mpn or part.mpn
                man = part.ref_manufacturer or part.manufacturer
                dnp = part.dnp or part.dnp_as_field
                # one line per physical part: identical parts share a line no matter how
                # the schematic annotated them (alternates are merged, not part of the key)
                key = (part.value, part.footprint, mpn, man, str(dnp))
                v_rows[key].append(ref)
                meta[key] = part
                alternates[key].update(part.alternates.split())
                flat.append(
                    {
                        "refdes": ref,
                        "value": part.value,
                        "footprint": part.footprint,
                        "mpn_in_schematic": part.mpn,
                        "dnp": dnp,
                    }
                )

    def nat(r: str) -> tuple[str, int]:
        i = next(i for i, ch in enumerate(r) if ch.isdigit())
        return (r[:i], int(r[i:]))

    rows = sorted(v_rows.items(), key=lambda kv: nat(sorted(kv[1], key=nat)[0]))
    with (out / "reference_bom.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(
            [
                "Reference",
                "Qty",
                "Value",
                "Footprint",
                "Manufacturer",
                "MPN",
                "MPN Alternates",
                "DNP",
            ]
        )
        for key, refs in rows:
            value, fp, mpn, man, dnp = key
            alts = " ".join(sorted(alternates[key]))
            w.writerow(
                [
                    " ".join(sorted(refs, key=nat)),
                    len(refs),
                    value,
                    fp,
                    man,
                    mpn,
                    alts,
                    "DNP" if dnp == "True" else "",
                ]
            )
    (out / "expected_components.json").write_text(
        json.dumps(sorted(flat, key=lambda d: nat(str(d["refdes"]))), indent=2) + "\n"
    )


# --------------------------------------------------------------------------- projects
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
YAGEO = "Yageo"


def ecg_frontend() -> Project:
    root = Sheet(
        "ecg-frontend.kicad_sch",
        [
            Part(
                "J1",
                "Connector_Generic:Conn_01x03",
                "Electrodes RA/LA/RL",
                "Connector_Molex:Molex_KK-254_AE-6410-03A_1x03_P2.54mm_Vertical",
                "22-23-2031",
                "Molex",
                description="ECG electrode connector",
            ),
            Part(
                "D1",
                "Device:D_TVS",
                "PESD5V0S1BA",
                "Diode_SMD:D_SOD-323",
                "PESD5V0S1BA",
                "Nexperia",
                description="ESD protection RA",
            ),
            Part(
                "D2",
                "Device:D_TVS",
                "PESD5V0S1BA",
                "Diode_SMD:D_SOD-323",
                "PESD5V0S1BA",
                "Nexperia",
                description="ESD protection LA",
            ),
            Part(
                "R1",
                "Device:R",
                "10M",
                R0603,
                ref_mpn="RC0603FR-0710ML",
                ref_manufacturer=YAGEO,
                description="Patient protection resistor",
            ),
            Part("R2", "Device:R", "10M", R0603, ref_mpn="RC0603FR-0710ML", ref_manufacturer=YAGEO),
            Part(
                "TP1",
                "Connector:TestPoint",
                "TestPoint",
                "TestPoint:TestPoint_Pad_D1.0mm",
                description="ECG output",
            ),
            Part("TP2", "Connector:TestPoint", "TestPoint", "TestPoint:TestPoint_Pad_D1.0mm"),
            Part(
                "H1",
                "Mechanical:MountingHole",
                "MountingHole",
                "MountingHole:MountingHole_3.2mm_M3",
                in_bom=False,
            ),
            Part(
                "H2",
                "Mechanical:MountingHole",
                "MountingHole",
                "MountingHole:MountingHole_3.2mm_M3",
                in_bom=False,
            ),
        ],
        children=[("AFE", "afe.kicad_sch"), ("Power", "power.kicad_sch")],
    )
    afe = Sheet(
        "afe.kicad_sch",
        [
            Part(
                "U1",
                "bomagent:AD8232",
                "AD8232",
                "Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm",
                "AD8232ACPZ-R7",
                "Analog Devices",
                description="Single-lead heart rate monitor front end",
            ),
            Part(
                "U2",
                "Amplifier_Operational:OPA333xxDBV",
                "OPA333",
                "Package_TO_SOT_SMD:SOT-23-5",
                "OPA333AIDBVR",
                "Texas Instruments",
            ),
            Part("R3", "Device:R", "10k", R0603, "RC0603FR-0710KL", YAGEO),
            Part("R4", "Device:R", "10k", R0603, "RC0603FR-0710KL", YAGEO),
            Part(
                "R5",
                "Device:R",
                "100k",
                R0603,
                ref_mpn="RC0603FR-07100KL",
                ref_manufacturer=YAGEO,
                alternates="ERJ-3EKF1003V CRCW0603100KFKEA",
            ),
            Part("R6", "Device:R", "1M", R0603, ref_mpn="RC0603FR-071ML", ref_manufacturer=YAGEO),
            Part("R7", "Device:R", "4k7", R0603, ref_mpn="RC0603FR-074K7L", ref_manufacturer=YAGEO),
            Part("R8", "Device:R", "180k", R0603, "RC0603FR-07180KL", YAGEO),
            Part(
                "R9",
                "Device:R",
                "0R",
                R0603,
                "RC0603JR-070RL",
                YAGEO,
                dnp=True,
                description="Optional bypass",
            ),
            Part(
                "C1",
                "Device:C",
                "100n",
                C0603,
                ref_mpn="GRM188R71H104KA93D",
                ref_manufacturer="Murata",
                alternates="CL10B104KB8NNNC",
            ),
            Part(
                "C2",
                "Device:C",
                "100n",
                C0603,
                ref_mpn="GRM188R71H104KA93D",
                ref_manufacturer="Murata",
                alternates="CL10B104KB8NNNC",
            ),
            Part("C3", "Device:C", "1n", C0603, "GRM188R71H102KA01D", "Murata"),
            Part("C4", "Device:C", "10n", C0603, "GRM188R71H103KA01D", "Murata"),
        ],
    )
    power = Sheet(
        "power.kicad_sch",
        [
            Part(
                "J2",
                "Connector_Generic:Conn_01x02",
                "Battery",
                "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal",
                "S2B-PH-K-S(LF)(SN)",
                "JST",
            ),
            Part(
                "U3",
                "Regulator_Linear:MCP1700x-330xxTT",
                "MCP1700-3.3",
                "Package_TO_SOT_SMD:SOT-23",
                "MCP1700T-3302E/TT",
                "Microchip",
            ),
            Part(
                "C5",
                "Device:C",
                "10u",
                C0603,
                ref_mpn="CL10A106KP8NNNC",
                ref_manufacturer="Samsung Electro-Mechanics",
            ),
            Part(
                "C6",
                "Device:C",
                "10u",
                C0603,
                ref_mpn="CL10A106KP8NNNC",
                ref_manufacturer="Samsung Electro-Mechanics",
            ),
            Part("C7", "Device:C", "100n", C0603, "GRM188R71H104KA93D", "Murata"),
            Part(
                "FB1",
                "Device:FerriteBead",
                "220R@100MHz",
                "Inductor_SMD:L_0603_1608Metric",
                "BLM18PG221SN1D",
                "Murata",
            ),
            Part(
                "D3",
                "Device:LED",
                "Green",
                "LED_SMD:LED_0603_1608Metric",
                "LTST-C191KGKT",
                "Lite-On",
            ),
            Part("R10", "Device:R", "1k", R0603, "RC0603FR-071KL", YAGEO),
        ],
    )
    return Project(
        "ecg-frontend", 20231120, "8.0", {s.file: s for s in (root, afe, power)}, root.file
    )


def pulse_ox() -> Project:
    root = Sheet(
        "pulse-ox.kicad_sch",
        [
            Part(
                "U1",
                "bomagent:MAX30102",
                "MAX30102",
                "bomagent:MAX30102_OESIP-14",
                "MAX30102EFD+T",
                "Analog Devices",
                description="Pulse oximetry and heart-rate sensor",
            ),
            Part(
                "U2",
                "Regulator_Linear:LP5907MFX-1.8",
                "LP5907-1.8",
                "Package_TO_SOT_SMD:SOT-23-5",
                "LP5907MFX-1.8/NOPB",
                "Texas Instruments",
            ),
            Part(
                "U3",
                "Regulator_Linear:MCP1700x-330xxTT",
                "MCP1700-3.3",
                "Package_TO_SOT_SMD:SOT-23",
                "MCP1700T-3302E/TT",
                "Microchip",
            ),
            Part(
                "R1",
                "Device:R",
                "4k7",
                R0603,
                "RC0603FR-074K7L",
                YAGEO,
                description="I2C SDA pull-up",
            ),
            Part(
                "R2",
                "Device:R",
                "4k7",
                R0603,
                "RC0603FR-074K7L",
                YAGEO,
                description="I2C SCL pull-up",
            ),
            Part(
                "R3",
                "Device:R",
                "4k7",
                R0603,
                "RC0603FR-074K7L",
                YAGEO,
                dnp_as_field=True,
                description="INT pull-up (optional)",
            ),
            Part(
                "C1",
                "Device:C",
                "100n",
                C0603,
                ref_mpn="GRM188R71H104KA93D",
                ref_manufacturer="Murata",
            ),
            Part(
                "C2",
                "Device:C",
                "100n",
                C0603,
                ref_mpn="GRM188R71H104KA93D",
                ref_manufacturer="Murata",
            ),
            Part("C3", "Device:C", "10u", C0603, "CL10A106KP8NNNC", "Samsung Electro-Mechanics"),
            Part("C4", "Device:C", "1u", C0603, "GRM188R61C105KA93D", "Murata"),
            Part(
                "J1",
                "Connector_Generic:Conn_01x04",
                "I2C + power",
                "Connector_JST:JST_PH_S4B-PH-K_1x04_P2.00mm_Horizontal",
                "S4B-PH-K-S(LF)(SN)",
                "JST",
            ),
        ],
    )
    return Project("pulse-ox", 20211014, "6.0", {root.file: root}, root.file)


def eeg_2ch() -> Project:
    root = Sheet(
        "eeg-2ch.kicad_sch",
        [
            Part(
                "J1",
                "Connector_Generic:Conn_01x05",
                "Electrodes",
                "Connector_Molex:Molex_KK-254_AE-6410-05A_1x05_P2.54mm_Vertical",
                "22-23-2051",
                "Molex",
            ),
            Part(
                "U1",
                "bomagent:ADS1292R",
                "ADS1292R",
                "Package_QFP:TQFP-32_5x5mm_P0.5mm",
                "ADS1292RIPBSR",
                "Texas Instruments",
                description="2-channel 24-bit AFE",
            ),
            Part(
                "C1",
                "Device:C",
                "100n",
                C0603,
                ref_mpn="GRM188R71H104KA93D",
                ref_manufacturer="Murata",
            ),
            Part(
                "C2",
                "Device:C",
                "10u",
                C0603,
                ref_mpn="CL10A106KP8NNNC",
                ref_manufacturer="Samsung Electro-Mechanics",
            ),
            Part(
                "Y1",
                "Device:Crystal",
                "2.048MHz",
                "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
                description="ADC clock (optional, internal oscillator used)",
                dnp=True,
            ),
        ],
        children=[("Channel A", "channel.kicad_sch"), ("Channel B", "channel.kicad_sch")],
    )
    channel = Sheet(
        "channel.kicad_sch",
        [
            Part(
                "U101",
                "Amplifier_Instrumentation:INA333xxDGK",
                "INA333",
                "Package_SO:MSOP-8_3x3mm_P0.65mm",
                "INA333AIDGKR",
                "Texas Instruments",
            ),
            Part(
                "U102",
                "Amplifier_Operational:OPA2333xxD",
                "OPA2333",
                "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                "OPA2333AIDR",
                "Texas Instruments",
                units=2,
                description="Dual op-amp, units A/B used",
            ),
            Part(
                "R101",
                "Device:R",
                "49k9",
                R0603,
                ref_mpn="RC0603FR-0749K9L",
                ref_manufacturer=YAGEO,
                description="INA gain resistor (G=3)",
            ),
            Part("R102", "Device:R", "1M", R0603, "RC0603FR-071ML", YAGEO),
            Part("R103", "Device:R", "1M", R0603, "RC0603FR-071ML", YAGEO),
            Part(
                "C101",
                "Device:C",
                "47n",
                C0603,
                ref_mpn="GRM188R71H473KA61D",
                ref_manufacturer="Murata",
            ),
            Part("C102", "Device:C", "100n", C0603, "GRM188R71H104KA93D", "Murata"),
        ],
    )
    remap_b = {
        "U101": "U201",
        "U102": "U202",
        "R101": "R201",
        "R102": "R202",
        "R103": "R203",
        "C101": "C201",
        "C102": "C202",
    }
    return Project(
        "eeg-2ch",
        20250114,
        "9.0",
        {s.file: s for s in (root, channel)},
        root.file,
        instance_refs={"Channel B": remap_b},
    )


def main(out_dir: str) -> None:
    base = Path(out_dir)
    for project in (ecg_frontend(), pulse_ox(), eeg_2ch()):
        out = base / project.name
        out.mkdir(parents=True, exist_ok=True)
        render(project, out)
        reference_bom(project, out)
        print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "evals/fixtures/kicad")

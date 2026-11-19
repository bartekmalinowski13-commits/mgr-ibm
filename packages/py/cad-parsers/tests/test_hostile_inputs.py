"""Regression tests from the security review of the M7 parsers: hostile or damaged input
must end in a ParseError (never a crash of the worker) and must not produce wrong
parts silently."""

from __future__ import annotations

import contextlib
import gzip
import io
import random
import struct
import tarfile
import time
import zipfile

import pytest

from bomagent_cad import FileRef, ParseError, detect, parse_files
from bomagent_cad.odbpp import OdbppParser
from bomagent_testing.data import FIXTURES


def _pdf(content: bytes) -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800]"
        b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )


def _one_text_object(cells: list[tuple[int, int, bytes]]) -> bytes:
    """Cells positioned with Tm inside ONE text object (pypdf joins them)."""
    shown = b" ".join(b"1 0 0 1 %d %d Tm (%s) Tj" % c for c in cells)
    return b"BT /F1 10 Tf " + shown + b" ET"


def test_pdf_cells_in_one_text_object_footer_and_unknown_dnp():
    cells = [
        (50, 700, b"Designator"), (150, 700, b"Value"), (300, 700, b"MPN"), (450, 700, b"DNP"),
        (50, 680, b"C1"), (150, 680, b"100n"), (300, 680, b"GRM155R71C104KA88D"),
        (450, 680, b"maybe"),
        (50, 666, b"R1-R3, U1.A"), (150, 666, b"10k"),
        (300, 40, b"Page 1 of 3"),
    ]  # fmt: skip
    design = parse_files([FileRef("bom.pdf", _pdf(_one_text_object(cells)))])
    by_ref = {c.refdes: c for c in design.components}
    assert by_ref["C1"].field("MPN") == "GRM155R71C104KA88D"  # footer not glued on
    assert set(by_ref) == {"C1", "R1", "R2", "R3"}
    assert any("'maybe' not understood" in lim for lim in design.limitations)
    assert any("'U1.A' is not a designator" in lim for lim in design.limitations)


def _zip(files: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


ODB = {
    "job/steps/pcb/layers/comp_+_top/components": b"CMP 0 0 0 0 N R1 RES\nPRP VALUE '10k'\n",
    "job/steps/pcb/eda/data": b"PKG R0603 1 -1 -1 1 1\n",
}


def test_damaged_archives_are_parse_errors():
    good = _zip(ODB)
    # corrupt the compressed data of the first member (CRC / deflate error)
    at = good.index(b"PK\x03\x04") + 30 + len(next(iter(ODB)))
    bad = good[:at] + bytes(b ^ 0xFF for b in good[at : at + 8]) + good[at + 8 :]
    with pytest.raises(ParseError):
        parse_files([FileRef("job.zip", bad)])
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in ODB.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    truncated = gzip.compress(raw.getvalue()[:700])
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("job.tgz", truncated)])
    assert err.value.code == "archive.malformed"


def test_multi_member_gzip_is_read_completely():
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in ODB.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    data = raw.getvalue()
    pigz_like = gzip.compress(data[:1024]) + gzip.compress(data[1024:])
    design = parse_files([FileRef("job.tgz", pigz_like)])
    assert [(c.refdes, c.footprint) for c in design.components] == [("R1", "R0603")]


def test_zip_with_a_huge_directory_is_not_loaded_by_sniff():
    # end-of-central-directory claiming one million entries
    eocd = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 0xFFFF - 1, 0xFFFF - 1, 0, 0, 0)
    eocd = eocd[:10] + struct.pack("<H", 60_000) + struct.pack("<H", 60_000) + eocd[14:]
    data = b"PK\x03\x04" + b"\0" * 100 + eocd
    start = time.perf_counter()
    assert OdbppParser().sniff(FileRef("big.zip", data)) == 0.0
    assert time.perf_counter() - start < 1.0


def test_invalid_designators_are_skipped_and_reported():
    xml = (
        b'<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Bom name="b"><BomItem '
        b'OEMDesignNumberRef="1" quantity="2"><RefDes name="R 1"/><RefDes name="R2"/></BomItem>'
        b"</Bom></IPC-2581>"
    )
    design = parse_files([FileRef("a.xml", xml)])
    assert [c.refdes for c in design.components] == ["R2"]
    assert any("'R 1' is not a designator" in lim for lim in design.limitations)
    odb = dict(ODB)
    odb["job/steps/pcb/layers/comp_+_top/components"] += b"CMP 0 0 0 0 N J1-2 X\n"
    design = parse_files([FileRef("job.zip", _zip(odb))])
    assert [c.refdes for c in design.components] == ["R1"]


def test_unknown_xml_encoding():
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("a.xml", b'<?xml version="1.0" encoding="x-foo"?><IPC-2581/>')])
    assert err.value.code == "xml.malformed"


def test_edif_reads_the_top_cell_and_is_linear():
    nested = (
        b"(edif d (library lib (cell R0 (view v (contents (instance X1 (viewRef v"
        b" (cellRef P (libraryRef lib))))))) (cell top (view v (contents (instance R1"
        b' (viewRef v (cellRef R0 (libraryRef lib))) (property VALUE (string "10k"))))))) '
        b"(design d (cellRef top (libraryRef lib))))"
    )
    design = parse_files([FileRef("a.edf", nested)])
    assert [c.refdes for c in design.components] == ["R1"]
    assert any("not expanded" in lim for lim in design.limitations)
    many = b"(edif d " + b" ".join(b"(instance I%d)" % i for i in range(40_000)) + b")"
    start = time.perf_counter()
    assert len(parse_files([FileRef("big.edf", many)]).components) == 40_000
    assert time.perf_counter() - start < 5.0


def test_dxf_title_block_and_notes_are_not_parts():
    import ezdxf

    doc = ezdxf.new()
    title = doc.blocks.new("TITLE")
    for i, tag in enumerate(("NO", "TITLE")):
        title.add_attdef(tag, (i * 30, 0))
    msp = doc.modelspace()
    msp.add_blockref("TITLE", (0, -60)).add_auto_attribs({"NO": "1", "TITLE": "Housing"})
    for x, text in ((0, "POS"), (15, "PART NUMBER"), (60, "DESCRIPTION")):
        msp.add_text(text, height=2.5, dxfattribs={"insert": (x, 0)})
    for row, (pos, pn, desc) in enumerate((("1", "A-1", "Shell"), ("2", "B-2", "Screw")), 1):
        for x, text in ((0, pos), (15, pn), (60, desc)):
            msp.add_text(text, height=2.5, dxfattribs={"insert": (x, row * 6)})
    msp.add_text("3", height=2.5, dxfattribs={"insert": (0, 300)})  # a drawing note
    msp.add_text("BREAK ALL SHARP EDGES", height=2.5, dxfattribs={"insert": (60, 300)})
    stream = io.StringIO()
    doc.write(stream)
    design = parse_files([FileRef("a.dxf", stream.getvalue().encode())])
    assert sorted((c.refdes, c.value) for c in design.components) == [
        ("MP1", "Shell"),
        ("MP2", "Screw"),
    ]


FUZZ_INPUTS = [
    FIXTURES / "ipc2581" / "pulse-ox.xml",
    FIXTURES / "edif" / "pulse-ox.edf",
    FIXTURES / "odbpp" / "pulse-ox.tgz",
    FIXTURES / "dxf" / "enclosure-attribs.dxf",
    FIXTURES / "pdf-bom" / "pulse-ox.pdf",
]


@pytest.mark.parametrize("path", FUZZ_INPUTS, ids=lambda p: p.name)
def test_fuzzed_files_only_raise_parse_errors(path):
    base = path.read_bytes()
    rng = random.Random(f"fuzz:{path.name}")
    for _ in range(60):
        data = bytearray(base)
        for _ in range(rng.randint(1, 12)):
            i = rng.randrange(len(data))
            data[i] = rng.randrange(256)
        if rng.random() < 0.3:
            data = data[: rng.randrange(len(data))]
        with contextlib.suppress(ParseError):  # anything else fails the test
            parse_files([FileRef(path.name, bytes(data))])


def test_registry_converts_unexpected_errors():
    class Exploding:
        format_id = "boom"
        version = "0"

        def sniff(self, file):
            return 1.0

        def parse(self, files):
            raise LookupError("library bug")

    with pytest.raises(ParseError) as err:
        parse_files([FileRef("x.bin", b"x")], [Exploding()])
    assert err.value.code == "parse.internal"
    assert detect([FileRef("x.bin", b"x")], [Exploding()]).format_id == "boom"


# --- ingest review (I2, I3, M3): budgets on real counts and real decompressed bytes ---------


def _kicad_sheet(body: str, uuid: str) -> bytes:
    head = f'(kicad_sch (version 20231120) (generator "eeschema") (uuid "{uuid}")\n'
    return (head + body + ")").encode()


def _kicad_symbols(count: int) -> str:
    # no instance data: the designator comes from the Reference field on every sheet instance
    return "\n".join(
        f'(symbol (lib_id "Device:R") (uuid "s{i}") (property "Reference" "R{i + 1}")'
        f' (property "Value" "10k"))'
        for i in range(count)
    )


def _kicad_entries(count: int) -> str:
    return "\n".join(
        f'(sheet (at 0 0) (size 1 1) (uuid "e{i}") (property "Sheetname" "ch{i}")'
        f' (property "Sheetfile" "child.kicad_sch"))'
        for i in range(count)
    )


def test_kicad_component_cap_counts_symbols_of_a_single_sheet(monkeypatch):
    from bomagent_cad import kicad

    monkeypatch.setattr(kicad, "MAX_COMPONENTS", 50)
    flat = FileRef("flat.kicad_sch", _kicad_sheet(_kicad_symbols(51), "root"))
    with pytest.raises(ParseError) as err:
        parse_files([flat])
    assert err.value.code == "kicad.too_complex"


def test_kicad_component_cap_counts_repeated_instances_of_a_hierarchical_sheet(monkeypatch):
    """A root with N sheet entries pointing at one child multiplies the child's symbols; every
    repeated instance is a duplicate designator and counts against the budget."""
    from bomagent_cad import kicad

    monkeypatch.setattr(kicad, "MAX_COMPONENTS", 50)
    root = FileRef("root.kicad_sch", _kicad_sheet(_kicad_entries(10), "root"))
    child = FileRef("child.kicad_sch", _kicad_sheet(_kicad_symbols(10), "child"))
    with pytest.raises(ParseError) as err:
        parse_files([root, child])
    assert err.value.code == "kicad.too_complex"


def test_kicad_fan_out_stops_early_before_building_everything(monkeypatch):
    """The abort happens while symbols are added, not after a whole sheet is built."""
    from bomagent_cad import kicad

    monkeypatch.setattr(kicad, "MAX_COMPONENTS", 100)
    added: list[int] = []
    original = kicad.KicadParser._add_symbol

    def counting(self, ctx, sym, path, sheet_path):
        added.append(1)
        return original(self, ctx, sym, path, sheet_path)

    monkeypatch.setattr(kicad.KicadParser, "_add_symbol", counting)
    root = FileRef("root.kicad_sch", _kicad_sheet(_kicad_entries(2), "root"))
    child = FileRef("child.kicad_sch", _kicad_sheet(_kicad_symbols(5_000), "child"))
    with pytest.raises(ParseError) as err:
        parse_files([root, child])
    assert err.value.code == "kicad.too_complex"
    assert len(added) <= 101


def test_registry_rejects_designs_above_the_component_cap(monkeypatch):
    from bomagent_bom.model import Component, ParsedDesign
    from bomagent_cad import registry

    monkeypatch.setattr(registry, "MAX_COMPONENTS", 3)

    class Generous:
        format_id = "generous"
        version = "0"

        def sniff(self, file):
            return 1.0

        def parse(self, files):
            return ParsedDesign(
                design_name="d",
                source_format="generous",
                components=[Component(refdes=f"R{i}", value="1k") for i in range(1, 5)],
                confidence=1.0,
            )

    with pytest.raises(ParseError) as err:
        parse_files([FileRef("x.bin", b"x")], [Generous()])
    assert err.value.code == "file.too_large"


def test_registry_enforces_the_file_size_limit_for_in_memory_files(monkeypatch):
    from bomagent_cad import registry

    monkeypatch.setattr(registry, "MAX_FILE_BYTES", 1024)
    xml = b'<IPC-2581 xmlns="http://webstds.ipc.org/2581">' + b" " * 2048 + b"</IPC-2581>"
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("big.xml", xml)])
    assert err.value.code == "file.too_large"


def _lie_about_size(data: bytes, name: str, declared: int) -> bytes:
    """Patch the uncompressed size of member ``name`` in its local header and in the central
    directory - the attacker controls both; the real deflate stream is unchanged."""
    out = bytearray(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        offset = z.getinfo(name).header_offset
    out[offset + 22 : offset + 26] = struct.pack("<I", declared)
    central = out.index(b"PK\x01\x02")
    while out[central : central + 4] == b"PK\x01\x02":
        n_len, x_len, c_len = struct.unpack("<HHH", out[central + 28 : central + 34])
        if bytes(out[central + 46 : central + 46 + n_len]) == name.encode():
            out[central + 24 : central + 28] = struct.pack("<I", declared)
        central += 46 + n_len + x_len + c_len
    return bytes(out)


_COMP = "job/steps/pcb/layers/comp_+_top/components"


def test_zip_member_lying_about_its_size_is_stopped_on_real_bytes(monkeypatch):
    """A member that declares 1000 bytes but inflates to megabytes stops at the budget,
    counted on the bytes actually decompressed (not on the central directory)."""
    from bomagent_cad import odbpp

    monkeypatch.setattr(odbpp, "MAX_TOTAL_BYTES", 64 * 1024)
    files = dict(ODB)
    files[_COMP] = ODB[_COMP] + b" " * (4 * 1024 * 1024)
    bomb = _lie_about_size(_zip(files), _COMP, 1000)
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("bomb.zip", bomb)])
    assert err.value.code == "archive.too_large"


def test_zip_member_inflating_past_its_declared_size_is_malformed():
    files = dict(ODB)
    files[_COMP] = ODB[_COMP] + b" " * 4096
    liar = _lie_about_size(_zip(files), _COMP, len(ODB[_COMP]))
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("liar.zip", liar)])
    assert err.value.code == "archive.malformed"


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_zip_members_with_unbounded_decompressors_are_refused(method):
    """``zipfile`` inflates a whole bzip2/LZMA input chunk at once: no streamed bound."""
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("job.zip", _zip(ODB, method))])
    assert err.value.code == "archive.unsupported"

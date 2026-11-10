"""ODB++ (M7): cross-format consistency, archive safety (traversal, bombs), detection."""

from __future__ import annotations

import io
import tarfile
import zipfile

import pytest

from bomagent_bom.model import ParsedDesign
from bomagent_cad import FileRef, ParseError, UnsupportedFormatError, detect, odbpp, parse_files
from bomagent_testing.data import FIXTURES, KICAD_PROJECTS, kicad_project_paths


def kicad(name: str) -> ParsedDesign:
    return parse_files([FileRef.from_path(p) for p in kicad_project_paths(name)])


def parts(design: ParsedDesign) -> list[tuple[str, str, str, str, str, bool]]:
    return sorted(
        (
            c.refdes,
            c.value,
            c.footprint.split(":")[-1],
            c.field("MPN"),
            c.field("Manufacturer"),
            c.dnp,
        )
        for c in design.bom_components()
    )


def members(name: str) -> dict[str, bytes]:
    with tarfile.open(FIXTURES / "odbpp" / f"{name}.tgz", "r:gz") as tar:
        return {
            m.name: tar.extractfile(m).read()  # type: ignore[union-attr]
            for m in tar.getmembers()
            if m.isfile()
        }


def tgz(files: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            link = tarfile.TarInfo(symlink)
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)
    return buf.getvalue()


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data)
    return buf.getvalue()


@pytest.mark.parametrize("name", KICAD_PROJECTS)
def test_odbpp_job_matches_the_kicad_design(name):
    design = parse_files([FileRef.from_path(FIXTURES / "odbpp" / f"{name}.tgz")])
    assert design.source_format == "odbpp"
    assert design.design_name == name
    assert design.confidence >= 0.9
    assert parts(design) == parts(kicad(name))


def test_zip_archive_and_bottom_side():
    files = members("pulse-ox")
    top = next(k for k in files if k.endswith("comp_+_top/components"))
    # move the components to the bottom side: the parser reads both sides
    files[top.replace("comp_+_top", "comp_+_bot")] = files.pop(top)
    design = parse_files([FileRef("pulse-ox.zip", zipped(files))])
    assert parts(design) == parts(kicad("pulse-ox"))


@pytest.mark.parametrize(
    "bad",
    ["../../etc/cron.d/x/steps/pcb/layers/comp_+_top/components", "/abs/steps/pcb/eda/data"],
)
def test_unsafe_member_paths_are_rejected(bad):
    files = members("pulse-ox") | {bad: b"CMP 0 0 0 0 N R1 X\n"}
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("evil.tgz", tgz(files))])
    assert err.value.code == "archive.unsafe_path"


def test_links_are_rejected():
    data = tgz(members("pulse-ox"), symlink="pulse-ox/steps/pcb/layers/comp_+_bot/components")
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("link.tgz", data)])
    assert err.value.code == "archive.unsafe_path"


def test_decompression_bombs_are_stopped(monkeypatch):
    monkeypatch.setattr(odbpp, "MAX_TOTAL_BYTES", 64 * 1024)
    bomb = members("pulse-ox") | {"pulse-ox/misc/padding": b"\0" * (1024 * 1024)}
    for data, name in ((tgz(bomb), "bomb.tgz"), (zipped(bomb), "bomb.zip")):
        with pytest.raises(ParseError) as err:
            parse_files([FileRef(name, data)])
        assert err.value.code == "archive.too_large"


def test_compressed_members_are_reported_not_guessed():
    files = members("pulse-ox")
    top = next(k for k in files if k.endswith("comp_+_top/components"))
    files[top + ".Z"] = files.pop(top)
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("compressed.tgz", tgz(files))])
    assert err.value.code == "odbpp.compressed_members"


def test_archives_that_are_not_odbpp_and_garbage():
    with pytest.raises(UnsupportedFormatError):
        detect([FileRef("photos.zip", zipped({"a.jpg": b"\xff\xd8"}))])
    with pytest.raises(UnsupportedFormatError):
        detect([FileRef("broken.tgz", b"not a gzip stream")])


def test_component_records_with_attributes_and_unknown_package():
    components = (
        b"UNITS=MM\n"
        b"CMP 7 1.0 2.0 90 Y U1 OPA333AIDBVR ;0=1\n"
        b"PRP VALUE 'OPA333 rail-to-rail'\n"
        b"PRP TOLERANCE '1%'\n"
        b"CMP 0 1.0 2.0 0 N R1 RC0603\n"
    )
    files = {
        "job/steps/pcb/layers/comp_+_top/components": components,
        "job/steps/pcb/eda/data": b"PKG R0603 1 -1 -1 1 1\n",
    }
    design = parse_files([FileRef("job.tgz", tgz(files))])
    by_ref = {c.refdes: c for c in design.components}
    assert by_ref["U1"].value == "OPA333 rail-to-rail"
    assert by_ref["U1"].fields["TOLERANCE"] == "1%"
    assert by_ref["U1"].footprint == ""  # package index 7 does not exist
    assert by_ref["R1"].footprint == "R0603"
    assert by_ref["R1"].fields["Part"] == "RC0603"
    assert any("package" in lim for lim in design.limitations)

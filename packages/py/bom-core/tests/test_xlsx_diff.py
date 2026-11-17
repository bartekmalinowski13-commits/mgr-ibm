from __future__ import annotations

import io
import zipfile

from bomagent_bom.diff import diff_versions
from bomagent_bom.export import to_xlsx
from bomagent_bom.model import BomItem, BomVersion


def test_xlsx_export_is_a_workbook_with_the_csv_table_and_no_formulas():
    bom = BomVersion(
        design_name="t",
        items=[
            BomItem(line=1, refdes=["R1", "R2"], quantity=2, value="=HYPERLINK(1)", mpn="A&B<1>")
        ],
    )
    data = to_xlsx(bom, demo=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"} <= set(
            zf.namelist()
        )
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet  # values are inline strings, never formulas
    assert "&lt;1&gt;" in sheet
    assert "A&amp;B" in sheet  # escaped
    assert '<c r="A2"><v>1</v></c>' in sheet  # numbers stay numbers
    assert "<t>Demo</t>" in sheet
    assert "illustrative" in sheet


def test_xlsx_export_carries_the_kb_snapshot_id():
    bom = BomVersion(design_name="t", items=[BomItem(line=1, refdes=["R1"], quantity=1)])
    with zipfile.ZipFile(io.BytesIO(to_xlsx(bom, kb_snapshot_id="kbs_abc"))) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "KB snapshot" in sheet
    assert "kbs_abc" in sheet


def test_xlsx_export_strips_characters_xml_cannot_hold():
    bom = BomVersion(
        design_name="t", items=[BomItem(line=1, refdes=["R1"], quantity=1, value="a\x00b\x07c")]
    )
    with zipfile.ZipFile(io.BytesIO(to_xlsx(bom))) as zf:
        assert "abc" in zf.read("xl/worksheets/sheet1.xml").decode()


def test_diff_versions_reports_added_removed_and_changed_lines():
    old = BomVersion(
        design_name="t",
        items=[
            BomItem(line=1, refdes=["R1"], quantity=1, mpn="OLD", value="10k"),
            BomItem(line=2, refdes=["C1"], quantity=1),
        ],
    )
    new = BomVersion(
        design_name="t",
        items=[
            BomItem(line=1, refdes=["R1"], quantity=1, mpn="NEW", value="10k"),
            BomItem(line=3, refdes=["U1"], quantity=1),
        ],
    )
    diff = diff_versions(old, new)
    assert [i.line for i in diff.added] == [3]
    assert [i.line for i in diff.removed] == [2]
    assert len(diff.changed) == 1
    change = diff.changed[0]
    assert change.line == 1
    assert [(f.field, f.before, f.after) for f in change.fields] == [("mpn", "OLD", "NEW")]
    same = diff_versions(old, old)
    assert (same.added, same.removed, same.changed) == ([], [], [])

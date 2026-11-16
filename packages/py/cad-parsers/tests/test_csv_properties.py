"""Property-based designator and CSV round trips (QA-03)."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bomagent_bom.export import to_csv
from bomagent_bom.grouping import group_components
from bomagent_bom.model import BomVersion, Component, ParsedDesign
from bomagent_bom.refdes import compress, sort_refdes
from bomagent_cad.base import FileRef
from bomagent_cad.csv_bom import CsvBomParser, expand_refdes

PROFILE = settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
REFDES = st.builds(
    lambda p, n: f"{p}{n}", st.sampled_from(["R", "C", "L", "D", "U", "J"]), st.integers(1, 300)
)
_COMPONENT = st.builds(
    lambda ref, value, mpn: Component(
        refdes=ref, value=value, footprint="F_0603", fields={"MPN": mpn} if mpn else {}
    ),
    REFDES,
    st.sampled_from(["10k", "100n", "4.7uF", "AD8232", "1 Ω"]),
    st.sampled_from(["", "ABC123", "X-9"]),
)


@PROFILE
@given(refs=st.lists(REFDES, min_size=1, max_size=40))
def test_compress_then_expand_keeps_every_designator(refs):
    assert expand_refdes(compress(refs)) == sort_refdes(refs)


@PROFILE
@given(components=st.lists(_COMPONENT, min_size=1, max_size=25, unique_by=lambda c: c.refdes))
def test_export_then_import_preserves_designators(components):
    design = ParsedDesign(
        design_name="p", source_format="kicad", components=components, confidence=1.0
    )
    items = group_components(design)
    csv_text = to_csv(BomVersion(design_name="p", items=items))
    parsed = CsvBomParser().parse([FileRef("bom.csv", csv_text.encode())])
    assert sort_refdes(c.refdes for c in parsed.components) == sort_refdes(
        c.refdes for c in components
    )
    assert not [x for x in parsed.limitations if "Qty" in x or "duplicate" in x]


@PROFILE
@given(cell=st.text(max_size=60))
def test_expand_refdes_never_raises_and_is_bounded(cell):
    assert len(expand_refdes(cell)) <= 1000 * max(1, len(cell))

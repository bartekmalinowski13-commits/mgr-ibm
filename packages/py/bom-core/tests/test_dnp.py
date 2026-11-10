import pytest

from bomagent_bom.dnp import parse_dnp


@pytest.mark.parametrize(
    ("cell", "column", "expected"),
    [
        ("DNP", "dnp", True),
        ("dnf", "dnp", True),
        ("Y", "dnp", True),
        ("", "dnp", False),
        ("N", "dnp", False),
        ("-", "dnp", False),
        ("Fitted", "dnp", False),
        ("n/a", "dnp", None),
        ("yes", "populate", False),
        ("", "populate", False),
        ("N", "populate", True),
        ("DNP", "populate", True),
        ("maybe", "populate", None),
    ],
)
def test_parse_dnp(cell, column, expected):
    assert parse_dnp(cell, column) is expected

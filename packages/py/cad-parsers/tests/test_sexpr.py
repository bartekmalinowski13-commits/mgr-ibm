from __future__ import annotations

import pytest

from bomagent_cad.sexpr import Atom, SexprError, SList, parse


def test_parse_nested_with_strings_and_escapes():
    tree = parse('(root (name "a \\"q\\" b\\n") (n 1.5) (flag yes))')
    assert tree.head == "root"
    assert tree.value("name") == 'a "q" b\n'
    assert tree.value("n") == "1.5"
    assert isinstance(tree.child("flag")[1], Atom)
    assert tree.value("missing", "d") == "d"


def test_value_of_list_child_returns_default():
    assert parse("(r (x (y 1)))").value("x", "-") == "-"


def test_head_of_empty_list():
    assert SList().head == ""


@pytest.mark.parametrize(
    "text",
    ["", "(a", "a)", "(a) (b)", '(a "x', '"x"', "atom", ")"],
)
def test_malformed(text):
    with pytest.raises(SexprError):
        parse(text)


def test_depth_and_token_limits():
    with pytest.raises(SexprError, match="deep"):
        parse("(" * 600 + ")" * 600)
    with pytest.raises(SexprError, match="tokens"):
        parse("(a " + "b " * 100 + ")", max_tokens=50)

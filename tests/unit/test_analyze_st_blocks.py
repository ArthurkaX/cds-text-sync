"""
test_analyze_st_blocks.py - Control-flow nesting scanner (Item 7).

Consumes blanked text, so keyword matching inside comments and strings is
already handled; these tests pin the pipeline (body + blanking + scanner)
against regressions. Offsets are absolute into ``unit.text``.
"""

from cds_static_analyzer import project as pm
from cds_static_analyzer.st.blocks import tree

from analyze_helpers import fixture_project_view


def _st(text):
    return pm._build_st_unit("x.st", "PROGRAM P\nIMPLEMENTATION\n" + text)


def _impl(text):
    unit = _st(text)
    root = tree(unit)
    return root, unit


def test_nested_if_inside_case_inside_for():
    root, unit = _impl(
        "FOR i := 0 TO 9 DO\n"
        "CASE x OF\n"
        "1: IF a THEN\n"
        "   y := 1;\n"
        "   END_IF\n"
        "END_CASE\n"
        "END_FOR\n"
    )
    assert not root.unbalanced
    assert [c.kind for c in root.children] == ["FOR"]
    _for = root.children[0]
    assert [c.kind for c in _for.children] == ["CASE"]
    case = _for.children[0]
    assert [c.kind for c in case.children] == ["IF"]
    assert case.depth == 2
    ifb = case.children[0]
    assert ifb.depth == 3


def test_elsif_chain_is_sibling_branches_not_nested_blocks():
    root, _ = _impl(
        "IF a THEN\nx := 1;\nELSIF b THEN\ny := 2;\nELSIF c THEN\nz := 3;\n"
        "ELSE\nw := 4;\nEND_IF\n"
    )
    ifb = root.children[0]
    assert len(ifb.children) == 0  # arms are branches, not nested blocks
    labels = [label for label, _s, _e in ifb.branches]
    assert labels == ["IF a", "ELSIF b", "ELSIF c", "ELSE"]


def test_repeat_until_end_repeat():
    root, _ = _impl(
        "REPEAT\nx := 1;\nUNTIL done\nEND_REPEAT\n"
    )
    assert [c.kind for c in root.children] == ["REPEAT"]
    rep = root.children[0]
    assert len(rep.branches) == 0
    assert rep.end_offset is not None
    assert not root.unbalanced


def test_case_labels_are_branches():
    root, _ = _impl(
        "CASE sel OF\n"
        "1: a := 1;\n"
        "2, 3: b := 2;\n"
        "ELSE\nc := 3;\n"
        "END_CASE\n"
    )
    case = root.children[0]
    assert [label for label, _s, _e in case.branches] == ["1", "2, 3", "ELSE"]
    assert [c.kind for c in case.children] == []


def test_keywords_in_comments_and_strings_are_ignored():
    root, _ = _impl(
        "// IF a THEN END_IF\n"
        "x := 'CASE y OF';\n"
        "(* FOR i := 0 DO *) \n"
        "IF a THEN\nEND_IF\n"
    )
    assert not root.unbalanced
    assert [c.kind for c in root.children] == ["IF"]


def test_identifier_containing_keyword_is_not_matched():
    root, _ = _impl(
        "IF END_IFX AND MYFOR THEN\nEND_IF\n"
    )
    assert not root.unbalanced
    assert len(root.children) == 1
    assert root.children[0].kind == "IF"
    # END_IFX is a symbol, not a closer; MYFOR is not a FOR opener.
    assert root.issues == []


def test_unbalanced_block_sets_flag_and_does_not_raise():
    root, _ = _impl("IF a THEN\nx := 1;\n")
    assert root.unbalanced
    assert root.children[0].kind == "IF"
    assert any("unterminated" in msg for _off, msg in root.issues)


def test_offsets_are_absolute_and_index_unit_text():
    root, unit = _impl("IF a THEN\n  x := 1;\nEND_IF\n")
    ifb = root.children[0]
    assert unit.text[ifb.start_offset] == "I"
    label, s, e = ifb.branches[0]
    assert unit.text[s] == "I"
    assert unit.text[ifb.end_offset] == "\n"  # exclusive end of END_IF
    # .at converted the local position by the implementation base.
    assert ifb.start_offset == unit.text.find("IF a THEN")


def test_empty_body_returns_root_without_children():
    unit = pm._build_st_unit("x.st", "PROGRAM P\n")
    root = tree(unit)
    assert root.children == []
    assert root.issues == []
    assert not root.unbalanced


def test_case_body_before_labels_is_not_a_branch():
    root, _ = _impl("CASE x OF\n1: y := 1;\nEND_CASE\n")
    case = root.children[0]
    labels = [label for label, _s, _e in case.branches]
    assert labels == ["1"]
    # The CASE selector "x" must not appear as a branch label.
    assert "x" not in labels


def test_fixture_most_nested_pou_is_correct():
    """Freeze the fixture project's deepest POU (FB_Conveyor.Run: a FOR
    around nothing else). The spec requires this tree to be hand-verified
    once and pinned so a scanner regression cannot go unnoticed."""
    snap = pm.build_snapshot(fixture_project_view())
    unit = snap.find_unit("POUs/FB_Conveyor.Run.st#FB_Conveyor.Run")
    root = tree(unit)
    assert not root.unbalanced
    assert [c.kind for c in root.children] == ["FOR"]
    _for = root.children[0]
    assert _for.depth == 1
    assert _for.children == []  # the FOR body is a single assignment
    assert _for.end_offset is not None
    assert unit.text[_for.start_offset] == "F"

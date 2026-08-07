"""Control-flow nesting scanner contract tests."""

from cds_static_analyzer import project as pm
from cds_static_analyzer.st.blocks import tree

from st_helpers import fixture_project_view


def _st(text):
    return pm._build_st_unit("x.st", "PROGRAM P\nIMPLEMENTATION\n" + text)


def _impl(text):
    unit = _st(text)
    return tree(unit), unit


def test_nested_if_inside_case_inside_for():
    root, _ = _impl("FOR i := 0 TO 9 DO\nCASE x OF\n1: IF a THEN\n   y := 1;\n   END_IF\nEND_CASE\nEND_FOR\n")
    assert not root.unbalanced
    assert [child.kind for child in root.children] == ["FOR"]
    _for = root.children[0]
    assert [child.kind for child in _for.children] == ["CASE"]
    case = _for.children[0]
    assert [child.kind for child in case.children] == ["IF"]
    assert case.depth == 2
    assert case.children[0].depth == 3


def test_elsif_chain_is_sibling_branches_not_nested_blocks():
    root, _ = _impl("IF a THEN\nx := 1;\nELSIF b THEN\ny := 2;\nELSIF c THEN\nz := 3;\nELSE\nw := 4;\nEND_IF\n")
    if_block = root.children[0]
    assert not if_block.children
    assert [label for label, _start, _end in if_block.branches] == ["IF a", "ELSIF b", "ELSIF c", "ELSE"]


def test_repeat_until_end_repeat():
    root, _ = _impl("REPEAT\nx := 1;\nUNTIL done\nEND_REPEAT\n")
    repeat = root.children[0]
    assert repeat.kind == "REPEAT"
    assert not repeat.branches
    assert repeat.end_offset is not None
    assert not root.unbalanced


def test_case_labels_are_branches():
    root, _ = _impl("CASE sel OF\n1: a := 1;\n2, 3: b := 2;\nELSE\nc := 3;\nEND_CASE\n")
    case = root.children[0]
    assert [label for label, _start, _end in case.branches] == ["1", "2, 3", "ELSE"]
    assert not case.children


def test_keywords_in_comments_and_strings_are_ignored():
    root, _ = _impl("// IF a THEN END_IF\nx := 'CASE y OF';\n(* FOR i := 0 DO *) \nIF a THEN\nEND_IF\n")
    assert not root.unbalanced
    assert [child.kind for child in root.children] == ["IF"]


def test_identifier_containing_keyword_is_not_matched():
    root, _ = _impl("IF END_IFX AND MYFOR THEN\nEND_IF\n")
    assert not root.unbalanced
    assert len(root.children) == 1
    assert root.children[0].kind == "IF"
    assert root.issues == []


def test_unbalanced_block_sets_flag_and_does_not_raise():
    root, _ = _impl("IF a THEN\nx := 1;\n")
    assert root.unbalanced
    assert root.children[0].kind == "IF"
    assert any("unterminated" in message for _offset, message in root.issues)


def test_offsets_are_absolute_and_index_unit_text():
    root, unit = _impl("IF a THEN\n  x := 1;\nEND_IF\n")
    if_block = root.children[0]
    assert unit.text[if_block.start_offset] == "I"
    _label, start, _end = if_block.branches[0]
    assert unit.text[start] == "I"
    assert unit.text[if_block.end_offset] == "\n"
    assert if_block.start_offset == unit.text.find("IF a THEN")


def test_empty_body_returns_root_without_children():
    root = tree(pm._build_st_unit("x.st", "PROGRAM P\n"))
    assert root.children == []
    assert root.issues == []
    assert not root.unbalanced


def test_tree_is_cached_per_unit():
    root, unit = _impl("IF ready THEN\nEND_IF\n")
    assert tree(unit) is root


def test_case_body_before_labels_is_not_a_branch():
    root, _ = _impl("CASE x OF\n1: y := 1;\nEND_CASE\n")
    labels = [label for label, _start, _end in root.children[0].branches]
    assert labels == ["1"]
    assert "x" not in labels


def test_fixture_most_nested_pou_is_correct():
    snap = pm.build_st_snapshot(fixture_project_view())
    unit = snap.find_unit("POUs/FB_Conveyor.Run.st#FB_Conveyor.Run")
    root = tree(unit)
    assert not root.unbalanced
    assert [child.kind for child in root.children] == ["FOR"]
    _for = root.children[0]
    assert _for.depth == 1
    assert _for.children == []
    assert _for.end_offset is not None
    assert unit.text[_for.start_offset] == "F"

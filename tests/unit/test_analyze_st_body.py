"""
test_analyze_st_body.py - Section access layer for rule text (Item 3).
"""

from cds_static_analyzer import project as pm
from cds_static_analyzer.st.body import body, declaration

# The implementation body starts after the IMPLEMENTATION marker plus a blank
# line, so a naive "body starts at 0" assumption lands in the VAR block.
_SNIPPET = (
    "PROGRAM P\n"
    "VAR\n"
    "  x : INT;\n"
    "END_VAR\n"
    "\n"
    "IMPLEMENTATION\n"
    "\n"
    "x := 1;\n"
    "y := 'a;b';\n"
    "// z := 2;\n"
    "w := 3;\n"
)


def _st(text):
    return pm._build_st_unit("snippet.st", text)


def test_body_offsets_are_absolute_and_land_in_unit_text():
    unit = _st(_SNIPPET)
    section = body(unit)
    # The first body character 'x' sits far from offset 0 (after the VAR
    # block and IMPLEMENTATION marker); .at must convert, not truncate.
    assert unit.text[section.at(0)] == "x"
    for needle in ("y := ", "w := 3"):
        local = section.text.find(needle)
        assert unit.text[section.at(local)] == needle[0]
        assert section.at(local) == unit.text.find(needle)


def test_body_blanked_text_keeps_comments_and_strings_out():
    section = body(_st(_SNIPPET))
    assert "z := 2" not in section.text
    assert "'a;b'" not in section.text
    # .raw is the untouched section text.
    assert "// z := 2;" in section.raw
    assert "y := 'a;b';" in section.raw


def test_declaration_offsets_are_absolute():
    unit = _st(_SNIPPET)
    section = declaration(unit)
    assert section
    local = section.text.find("x : INT")
    assert unit.text[section.at(local)] == "x"


def test_body_without_implementation_uses_whole_text():
    # A unit without an IMPLEMENTATION marker is analysed as its whole text
    # (the legacy rule fallback), with base 0 so offsets stay absolute.
    unit = _st("VAR_GLOBAL\n  g_x : INT;\nEND_VAR\n")
    section = body(unit)
    assert section
    assert section.base == 0
    assert "VAR_GLOBAL" in section.raw
    local = section.text.find("g_x")
    assert unit.text[section.at(local)] == "g"


def test_body_is_falsy_when_text_is_empty():
    assert not body(_st(""))


def test_declaration_is_falsy_when_absent():
    unit = pm._build_xml_unit("snippet.xml", "<Visualization></Visualization>")
    assert not declaration(unit)


def test_statements_split_at_real_semicolons_only():
    section = body(_st(_SNIPPET))
    assert [text for _offset, text in section.statements()] == [
        "x := 1",
        "y := '   '",
        "w := 3",
    ]


def test_statements_split_across_lines():
    unit = _st(
        "PROGRAM P\nIMPLEMENTATION\n"
        "result := a +\n"
        "    b;\n"
    )
    statements = list(body(unit).statements())
    assert len(statements) == 1
    offset, statement = statements[0]
    assert statement == "result := a +\n    b"
    assert unit.text[offset] == "r"


def test_semicolon_in_string_does_not_split():
    unit = _st(
        "PROGRAM P\nIMPLEMENTATION\n"
        "x := 1;\n"
        "msg := 'a;b;c';\n"
        "y := 2;\n"
    )
    assert [text for _o, text in body(unit).statements()] == [
        "x := 1",
        "msg := '     '",
        "y := 2",
    ]


def test_semicolon_in_comment_does_not_split():
    unit = _st(
        "PROGRAM P\nIMPLEMENTATION\n"
        "x := 1; (* keep ; here *)\n"
        "y := 2; // and ; here\n"
    )
    assert [text for _o, text in body(unit).statements()] == [
        "x := 1",
        "y := 2",
    ]


def test_lines_yield_lineno_absolute_offset_and_raw_text():
    unit = _st(_SNIPPET)
    lines = list(body(unit).lines())
    assert lines[0] == (1, body(unit).at(0), "x := 1;")
    assert unit.text[lines[0][1]] == "x"
    assert lines[1][2] == "y := 'a;b';"
    assert unit.text[lines[1][1]] == "y"
    assert lines[3][2] == "w := 3;"
    assert unit.text[lines[3][1]] == "w"

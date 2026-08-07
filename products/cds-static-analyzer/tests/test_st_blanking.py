"""Comment/string blanking offset invariants."""

from cds_static_analyzer.st.blanking import blank_noise, trim_strings

_CORPUS = [
    "a := 1; // line comment\nb := 2;",
    "a := 1; (* block *) b := 2;",
    "a := 1; (* (* nested-looking *) b := 2;",
    "a := 1; (* unterminated to EOF",
    "a := 1; {pragma} b := 2;",
    "a := 1; (* 'quote' *) b := 2;",
    "x := '// inside string';\n",
    "a := 1; (* multi\nline\ncomment *) b := 2;",
]


def _assert_invariant(text):
    blanked = blank_noise(text)
    assert len(blanked) == len(text)
    for index, char in enumerate(text):
        if char == "\n":
            assert blanked[index] == "\n"
    assert len(trim_strings(blanked)) == len(text)


def test_blank_noise_preserves_length_and_newlines():
    for text in _CORPUS:
        _assert_invariant(text)


def test_block_comment_terminator_keeps_its_bytes():
    text = "a := 1; (* n *) b := 2;"
    assert blank_noise(text) == "a := 1;" + " " * 9 + "b := 2;"
    assert len(blank_noise(text)) == len(text)


def test_blank_noise_blanks_terminated_and_unterminated_blocks():
    assert "n" not in blank_noise("a := 1; (* n *) b := 2;")
    text = "a := 1; (* still open"
    blanked = blank_noise(text)
    assert len(blanked) == len(text)
    assert blanked.endswith(" " * len("(* still open"))


def test_blank_noise_handles_nested_pragmas():
    text = "x := 1; {attribute 'x' := '{nested}'} y := 2;"
    blanked = blank_noise(text)
    assert len(blanked) == len(text)
    assert "y := 2;" in blanked
    assert "nested" not in blanked


def test_trim_strings_preserves_length_after_blanking():
    text = "msg := 'a//b;(*c*)';\n"
    double = trim_strings(blank_noise(text))
    assert len(double) == len(text)
    assert double.startswith("msg := '") and double.endswith("';\n")
    assert "//" not in double and "(*" not in double

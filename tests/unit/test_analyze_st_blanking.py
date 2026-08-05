"""
test_analyze_st_blanking.py - blank_noise/trim_strings offset invariants.

A blanking bug that drops bytes silently shifts every later rule match: any
rule that reports ``section.at(match.start())`` would land one column too far
left per dropped byte. The length invariant below is stronger than testing
any one rule.
"""

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
    for i, ch in enumerate(text):
        if ch == "\n":
            # Newlines must survive blanking in place: line numbers depend
            # on them, and a lost newline reflows everything below it.
            assert blanked[i] == "\n"
    double = trim_strings(blanked)
    assert len(double) == len(text)


def test_blank_noise_preserves_length_and_newlines():
    for text in _CORPUS:
        _assert_invariant(text)


def test_block_comment_terminator_keeps_its_bytes():
    # The regression: the "(* n *)" branch consumed the two characters "* )"
    # but emitted one space, so the blanked text was one byte short and every
    # later match offset drifted left by one per block comment.
    text = "a := 1; (* n *) b := 2;"
    assert blank_noise(text) == "a := 1;" + " " * 9 + "b := 2;"
    assert len(blank_noise(text)) == len(text)


def test_blank_noise_blanks_terminated_and_unterminated_blocks():
    assert "n" not in blank_noise("a := 1; (* n *) b := 2;")
    # An unterminated block runs to EOF without raising and without losing
    # its own characters.
    text = "a := 1; (* still open"
    blanked = blank_noise(text)
    assert len(blanked) == len(text)
    assert blanked.endswith(" " * len("(* still open"))


def test_trim_strings_preserves_length_after_blanking():
    # trim_strings blanks string contents but keeps delimiters, so length is
    # preserved too once blank_noise no longer drops bytes.
    text = "msg := 'a//b;(*c*)';\n"
    double = trim_strings(blank_noise(text))
    assert len(double) == len(text)
    assert double.startswith("msg := '") and double.endswith("';\n")
    assert "//" not in double and "(*" not in double

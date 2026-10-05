# -*- coding: utf-8 -*-
"""Regression tests for the shared ST blanker.

``blanking`` used to exist three times -- ``cts_shared.st.blanking``,
``cds_static_analyzer.st.blanking`` and
``cds_text_sync.engine.variable_map._blank_noise`` -- with byte-identical
output.  They are one implementation now, reached through those import paths,
and these tests pin the behaviour on a corpus of edge cases so the
consolidation stays lossless.
"""

import os

import pytest

from cts_shared.st import blanking as shared
from cds_static_analyzer.st import blanking as analyzer
from cds_text_sync.engine import variable_map

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Edge cases the lexer must handle: nesting, EOF endings, CRLF, and every
# construct that switches it out of plain-text mode.
_EDGE_CASES = [
    "a := 1; // line comment\nb := 2;",
    "a := 1; (* block *) b := 2;",
    "a := 1; (* (* nested-looking *) b := 2;",
    "a := 1; (* unterminated to EOF",
    "a := 1; {pragma} b := 2;",
    "a := 1; {p {nested {deep} } } b := 2;",
    "a := 1; {unterminated pragma",
    "a := 1; (* 'quote' *) b := 2;",
    "x := '// inside string';\n",
    'x := "// inside double";\n',
    "a := 1; (* multi\nline\ncomment *) b := 2;",
    "s := 'it$\\'s';\n",
    "x := 1; /* C-style */ y := 2;",
    "x := 1; // (* not a block *) y := 2;\n",
    "x := 1; (* // not a line *) y := 2;",
    "a\r\nb := 1; // c\r\n",
    "a := 1; (* c\r\nd *) b := 2;\r\n",
    "'",
    '"',
    "/",
    "(",
    "{",
    "",
    "\n",
    "(*",
    "//",
    "{",
]

# (input, expected blank_noise output), captured from the unified lexer.
_GOLDEN = [
    ("a := 1; // c\nb := 2;", "a := 1;     \nb := 2;"),
    ("a := 1; (* c *) b := 2;", "a := 1;         b := 2;"),
    ("a := 1; (* open", "a := 1;        "),
    ("x := 1; {p {n} q} y := 2;", "x := 1;           y := 2;"),
    ("x := '// not a comment';\n", "x := '// not a comment';\n"),
    ("a := 1; /* not handled */ b := 2;", "a := 1; /* not handled */ b := 2;"),
    (
        "a := 1; (* (* inner *) tail *) b := 2;",
        "a := 1;                tail *) b := 2;",
    ),
    ("s := 'it$'s';\n", "s := 'it$'s';\n"),
]


def _repo_samples():
    """Every ``*.st`` in the repo, alongside the synthetic edge cases."""
    samples = list(_EDGE_CASES)
    for base, _dirs, files in os.walk(_ROOT):
        if os.sep + "." in base or "build" in base or "dist" in base:
            continue
        for name in files:
            if name.endswith(".st"):
                with open(os.path.join(base, name), encoding="utf-8", errors="replace") as fh:
                    samples.append(fh.read())
    return samples


def test_blank_noise_is_a_single_implementation():
    assert analyzer.blank_noise is shared.blank_noise
    assert variable_map._blank_noise is shared.blank_noise


def test_comment_spans_is_a_single_implementation():
    assert analyzer.comment_spans is shared.comment_spans


def test_has_intentional_noop_comment_is_shared():
    assert analyzer.has_intentional_noop_comment is shared.has_intentional_noop_comment
    assert shared.has_intentional_noop_comment("// wait\n\nend_if;", 8) is True
    assert shared.has_intentional_noop_comment("// nothing here\nend_if;", 8) is False


def test_blanked_is_the_trim_then_blank_pipeline():
    text = "a := 1; (* c *)"
    assert shared.blanked(text) == shared.trim_strings(shared.blank_noise(text))


@pytest.mark.parametrize("text,expected", _GOLDEN)
def test_blank_noise_golden(text, expected):
    assert shared.blank_noise(text) == expected


@pytest.mark.parametrize("text,expected", _GOLDEN)
def test_blank_noise_preserves_length(text, expected):
    assert len(expected) == len(text)


def test_blank_noise_preserves_offsets_over_the_corpus():
    for text in _repo_samples():
        blanked = shared.blank_noise(text)
        assert len(blanked) == len(text)
        for index, char in enumerate(text):
            if char == "\n":
                assert blanked[index] == "\n"


def test_comment_spans_reconstruct_the_comments():
    assert shared.comment_spans("a // c\nb") == [(2, 6, " c")]
    assert shared.comment_spans("a (* c *) b") == [(2, 9, " c ")]
    assert shared.comment_spans("x 'q' (* c *)") == [(6, 13, " c ")]


def test_trim_strings_is_a_single_implementation():
    assert analyzer.trim_strings is shared.trim_strings


def test_trim_strings_preserves_length_with_doubled_quote():
    """The escaped-quote branch keeps two spaces for the two characters it
    consumed, so the result stays as long as its input."""
    text = "s := 'a''b';\n"
    assert shared.trim_strings(text) == "s := '    ';\n"
    assert len(shared.trim_strings(text)) == len(text)


def test_trim_strings_preserves_length_over_the_corpus():
    for text in _repo_samples():
        assert len(shared.trim_strings(text)) == len(text)

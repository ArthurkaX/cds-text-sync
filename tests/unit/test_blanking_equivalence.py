# -*- coding: utf-8 -*-
"""Differential characterisation of the three ``blank_noise`` copies.

``blanking`` exists three times: ``cts_shared.st.blanking`` (the IronPython
copy the CODESYS host runs), ``cds_static_analyzer.st.blanking`` (the
analyzer's fork) and ``cds_text_sync.engine.variable_map._blank_noise``.  This
module pins what is equal between them today so a later consolidation cannot
change behaviour by accident, and pins the one place they differ so the
difference stays a known, deliberate one.

Nothing here asserts that the copies *should* diverge -- a test failing after a
consolidation means the consolidation changed an output, which is exactly the
signal worth having.
"""

import os

import pytest

from cts_shared.st import blanking as shared
from cds_static_analyzer.st import blanking as analyzer
from cds_text_sync.engine import variable_map

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Edge cases the three copies must agree on: nesting, escapes, EOF endings,
# CRLF, and every construct that switches the lexer out of plain-text mode.
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


def _id_of(text):
    return repr(text[:40])


def test_blank_noise_equivalent_across_copies():
    """All three copies blank byte-for-byte identically, offsets included."""
    for text in _repo_samples():
        reference = shared.blank_noise(text)
        assert analyzer.blank_noise(text) == reference
        assert variable_map._blank_noise(text) == reference
        assert len(reference) == len(text)


def test_comment_spans_equivalent_across_copies():
    for text in _repo_samples():
        assert analyzer.comment_spans(text) == shared.comment_spans(text)


def test_trim_strings_differ_only_on_doubled_quote_escapes():
    """The analyzer's copy is one byte short per ``''`` escape.

    ``cts_shared`` writes two spaces for a doubled quote (it consumed two
    characters); the analyzer writes one.  Every other input agrees, so the
    divergence is entirely explained by that branch.
    """
    unexplained = []
    for text in _repo_samples():
        a = shared.trim_strings(text)
        b = analyzer.trim_strings(text)
        if a != b and "''" not in text:
            unexplained.append(text)
    assert unexplained == []


def test_trim_strings_analyzer_length_bug_is_pinned():
    """Characterise the divergence so a fix shows up as a test change."""
    text = "s := 'a''b';\n"
    assert len(text) == 13
    fixed = shared.trim_strings(text)
    buggy = analyzer.trim_strings(text)
    assert fixed == "s := '    ';\n"
    assert len(fixed) == len(text)
    assert buggy == "s := '   ';\n"
    assert len(buggy) == len(text) - 1


def test_shared_only_helpers_are_absent_from_the_analyzer():
    """``blanked`` and ``has_intentional_noop_comment`` are each copy-only.

    A consolidation has to keep both names: the shared pipeline is what the
    block scanner consumes, and the no-op predicate is what CTS0037 consumes.
    """
    assert shared.blanked("a := 1; (* c *)") == shared.trim_strings(
        shared.blank_noise("a := 1; (* c *)")
    )
    assert not hasattr(analyzer, "blanked")
    assert not hasattr(shared, "has_intentional_noop_comment")


@pytest.mark.parametrize(
    "snippet",
    [
        "a := 1; (* n *) b := 2;",
        "x := 'it$\\'s';\n",
        "a := 1; {p {n} q} b := 2;",
        "a := 1; (* still open",
    ],
)
def test_blank_noise_offsets_survive_on_edge_cases(snippet):
    blanked = shared.blank_noise(snippet)
    assert len(blanked) == len(snippet)
    for index, char in enumerate(snippet):
        if char == "\n":
            assert blanked[index] == "\n"

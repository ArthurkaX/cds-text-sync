# -*- coding: utf-8 -*-
"""
test_visu_lint.py -- Tests for the sketch design checks.

``cts visu check`` validates a compiled screen; this module covers the checks
that run one step earlier, on the authored SVG, for the things that make a
technically valid screen look unfinished. The tests here pin the two properties
that make the rule set usable: it must fire on the real defects, and ``--fix``
must never damage a sketch it does not understand.
"""

import os
import re
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cli.visu import commands, lint


def _svg(body, width=800, height=480):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}">'
        "{2}</svg>".format(width, height, body)
    )


def _rules(findings):
    return sorted(set(f.rule for f in findings))


def _by_rule(findings, rule):
    return [f for f in findings if f.rule == rule]


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def test_clean_sketch_reports_nothing():
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="24" y="88" width="368" height="296"/>')
    )
    assert findings == []


def test_off_grid_rect_is_flagged_and_fixable():
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="23" y="89" width="367" height="295"/>')
    )
    grid = _by_rule(findings, "grid")
    assert len(grid) == 1
    assert grid[0].fixes == {"x": "24", "y": "88", "width": "368", "height": "296"}


def test_rect_corner_radius_is_not_grid_snapped():
    """``rx`` on a <rect> is a corner radius, not a position.

    Snapping it would round a deliberate 2px radius down to a square corner --
    the rule would be actively destroying a design choice rather than
    correcting a slip. On an <ellipse> the same attribute is a semi-axis and
    stays graded.
    """
    findings, _ = lint.lint_svg(
        _svg('<rect class="card" x="24" y="88" width="368" height="296" rx="2"/>')
    )
    assert findings == []

    findings, _ = lint.lint_svg(
        _svg('<ellipse class="metal" cx="120" cy="248" rx="63" ry="88"/>')
    )
    assert _by_rule(findings, "grid")[0].fixes == {"rx": "64"}


def test_text_baseline_is_graded_through_the_compiled_box_top():
    """A <text> y is a baseline, so the *box top* is what has to land on grid.

    Snapping the baseline itself would push the box off the grid, which is the
    opposite of what the rule is for. A 12px label at y=265 compiles to a box
    top of 253; the fix moves the baseline by the same -1 the top needs.
    """
    findings, _ = lint.lint_svg(_svg('<text class="label" x="24" y="265">Speed</text>'))
    assert _by_rule(findings, "grid")[0].fixes == {"y": "264"}

    findings, _ = lint.lint_svg(_svg('<text class="label" x="24" y="264">Speed</text>'))
    assert findings == []


def test_font_size_outside_the_scale_is_flagged():
    findings, _ = lint.lint_svg(_svg('<text x="24" y="36" font-size="14">Hi</text>'))
    scale = _by_rule(findings, "font-scale")
    assert len(scale) == 1
    assert scale[0].fixes == {"font-size": "12"}


def test_button_too_small_to_press_is_flagged():
    findings, _ = lint.lint_svg(
        _svg(
            '<rect data-cds-type="button" x="24" y="408" width="40" height="24"'
            ' data-text="Go" data-cds-tap="TAP HMI.Go"/>'
        )
    )
    assert _by_rule(findings, "touch-size")


def test_button_without_caption_or_action_is_flagged():
    """A <rect> cannot carry text content, so a missing data-text is silent."""
    findings, _ = lint.lint_svg(
        _svg('<rect data-cds-type="button" x="24" y="408" width="160" height="48"/>')
    )
    assert _by_rule(findings, "empty-button")
    assert _by_rule(findings, "inert-button")


def test_text_wider_than_its_box_is_flagged():
    findings, _ = lint.lint_svg(
        _svg(
            '<text data-cds-type="textfield" x="24" y="100" data-width="24"'
            ' data-height="32" data-text-var="HMI.V" font-size="12">'
            "a very long format string</text>"
        )
    )
    assert _by_rule(findings, "text-overflow")


def test_unbound_textfield_is_flagged():
    findings, _ = lint.lint_svg(
        _svg(
            '<text data-cds-type="textfield" x="24" y="100" data-width="200"'
            ' data-height="32" font-size="12">%3.1f</text>'
        )
    )
    assert _by_rule(findings, "unbound-field")


def test_out_of_bounds_element_is_an_error_and_suppresses_margin_advice():
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="700" y="88" width="368" height="296"/>')
    )
    assert [f.severity for f in _by_rule(findings, "bounds")] == ["error"]
    assert not _by_rule(findings, "margin")


def test_overlap_severity_depends_on_what_is_covered():
    """Two plain shapes crossing is how a P&ID is drawn; a covered control is not."""
    decorative = _svg(
        '<rect class="metal" x="24" y="24" width="100" height="100"/>'
        '<rect class="pipe-water" x="100" y="60" width="100" height="8"/>'
    )
    findings, _ = lint.lint_svg(decorative)
    assert [f.severity for f in _by_rule(findings, "overlap")] == ["info"]

    covering = _svg(
        '<rect class="metal" x="24" y="24" width="100" height="100"/>'
        '<rect data-cds-type="button" x="100" y="60" width="160" height="48"'
        ' data-text="Go" data-cds-tap="TAP HMI.Go"/>'
    )
    findings, _ = lint.lint_svg(covering)
    assert [f.severity for f in _by_rule(findings, "overlap")] == ["warn"]


def test_nesting_is_not_reported_as_overlap():
    findings, _ = lint.lint_svg(
        _svg(
            '<rect class="panel" x="24" y="88" width="368" height="296"/>'
            '<rect class="card" x="40" y="104" width="336" height="96"/>'
        )
    )
    assert not _by_rule(findings, "overlap")


def test_near_miss_gap_is_reported_as_crowding():
    findings, _ = lint.lint_svg(
        _svg(
            '<rect class="card" x="24" y="24" width="100" height="100"/>'
            '<rect class="card" x="128" y="24" width="100" height="100"/>'
        )
    )
    crowding = _by_rule(findings, "crowding")
    assert len(crowding) == 1
    assert "4px apart horizontally" in crowding[0].message


# ---------------------------------------------------------------------------
# --fix
# ---------------------------------------------------------------------------


def test_apply_fixes_rewrites_only_the_flagged_attributes():
    svg = _svg(
        "\n  <!-- a comment that must survive -->\n"
        '  <rect class="panel" x="23" y="89" width="367" height="295"/>\n'
    )
    findings, _ = lint.lint_svg(svg)
    fixed, count = lint.apply_fixes(svg, findings)

    assert count == 4
    assert "a comment that must survive" in fixed
    assert 'x="24" y="88" width="368" height="296"' in fixed
    # The fixed sketch is clean, and fixing again is a no-op.
    again, _ = lint.lint_svg(fixed)
    assert again == []
    assert lint.apply_fixes(fixed, again) == (fixed, 0)


def test_apply_fixes_leaves_a_clean_sketch_byte_identical():
    svg = _svg('<rect class="panel" x="24" y="88" width="368" height="296"/>')
    findings, _ = lint.lint_svg(svg)
    assert lint.apply_fixes(svg, findings) == (svg, 0)


def test_defs_block_is_not_indexed_as_a_drawable():
    """An inline :root theme block contains no drawables, and must not shift indices.

    ``index_source_tags`` and ``parse_svg`` have to walk the document the same
    way or every finding after a <defs> would point at the wrong element -- and
    --fix would then rewrite an innocent bystander.
    """
    svg = _svg(
        "<defs><style>:root { --water: #123456; }</style></defs>"
        '<rect class="pipe-water" x="23" y="24" width="100" height="8"/>'
    )
    findings, parsed = lint.lint_svg(svg)
    assert len(lint.index_source_tags(svg)) == len(parsed["elements"]) == 1
    assert _by_rule(findings, "grid")[0].fixes == {"x": "24"}


# ---------------------------------------------------------------------------
# The scaffold and the shipped examples have to pass their own checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size", [(800, 480), (1024, 600), (1280, 800), (640, 400), (480, 320)]
)
def test_composed_skeleton_lints_clean_at_every_size(size):
    """``cts visu new`` must hand back a sketch that already passes lint.

    The skeleton is composed from layout tokens rather than copied from a fixed
    file, so each canvas size takes a different branch -- narrow ones drop to a
    single KPI card, short ones drop the lamp rows. Every branch still has to
    parse and lint clean, or the first thing an author sees is a list of
    complaints about code they did not write.
    """
    width, height = size
    text = commands.compose_skeleton(width, height, "Test Screen")
    findings, parsed = lint.lint_svg(text)
    assert findings == [], [f.message for f in findings]
    assert (parsed["canvas"]["width"], parsed["canvas"]["height"]) == (width, height)


def test_composed_skeleton_comment_is_well_formed_xml():
    """``--`` is illegal inside an XML comment, and the guidance block is large.

    Naming a flag in the sketch's own comment (``cts visu lint --fix``) makes
    the whole file unparseable, and the failure surfaces as a ParseError on
    line 5 rather than as anything about comments.
    """
    text = commands.compose_skeleton(800, 480, "Test Screen")
    for comment in re.findall(r"<!--(.*?)-->", text, re.DOTALL):
        assert "--" not in comment


_EXAMPLES = os.path.join(_ROOT, "skills", "cds-visu-svg", "examples")


@pytest.mark.parametrize("name", ["status-panel.svg", "pid-schematic.svg"])
def test_shipped_examples_lint_clean(name):
    """SKILL.md tells an authoring model to copy from these files.

    Whatever they do, a generated screen will do too -- so a defect here is a
    defect in every screen built from them.
    """
    with open(os.path.join(_EXAMPLES, name), "r", encoding="utf-8") as handle:
        findings, _ = lint.lint_svg(handle.read())
    assert findings == [], [f.message for f in findings]

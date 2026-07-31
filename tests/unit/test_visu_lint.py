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

from cds_text_sync.visu import commands, lint, svg_import


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
        _svg(
            '<rect class="panel" x="24" y="88" width="368" height="296"/>'
            '<text class="label" x="40" y="124">In here</text>'
        )
    )
    assert findings == [], [f.message for f in findings]


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
        _svg('<rect class="panel" x="24" y="88" width="368" height="296" rx="2">'
             '</rect><text class="label" x="40" y="120">Flow</text>')
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
    # The button starts inside the vessel and runs out of it, so it is filed as
    # an overflow -- but a covered *control* is still a warn either way.
    assert [f.severity for f in _by_rule(findings, "overflow")] == ["warn"]


def test_a_child_running_out_of_its_parent_is_an_overflow():
    """"Card overlaps label" points at the wrong element.

    Only one of the two is wrong when a caption runs past the card holding it,
    and it is not the card. Naming it an overflow and filing it against the
    child says which one to resize.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<rect class="card" x="24" y="24" width="100" height="100"/>'
            '<text class="label" x="100" y="60" data-width="80">Sticks out</text>'
        )
    )
    assert not _by_rule(findings, "overlap")
    overflow = _by_rule(findings, "overflow")
    assert len(overflow) == 1
    assert overflow[0].index == 1  # the label, not the card
    assert overflow[0].message.startswith("label #1")


def test_two_siblings_in_the_same_place_stay_an_overlap():
    """Neither is inside the other -- they are simply colliding."""
    findings, _ = lint.lint_svg(
        _svg(
            '<text class="label" x="48" y="244" data-width="80">Delivered</text>'
            '<text class="label" x="48" y="252" data-width="80">Rejected</text>'
        )
    )
    assert _by_rule(findings, "overlap")
    assert not _by_rule(findings, "overflow")


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


def test_butting_pid_shapes_are_not_crowding():
    """A duct run meeting the equipment it feeds is a P&ID, not a near-miss.

    The crowding rule reads a 4px gap as a slip, which it is between two cards.
    Between a pipe and the vessel it enters it is the drawing being correct, and
    flagging it taught more than one author to pull the process apart until it
    stopped reading as a process.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<rect class="pipe-water" x="24" y="120" width="100" height="8"/>'
            '<rect class="metal" x="128" y="104" width="40" height="40"/>'
            '<rect class="pipe-water" x="172" y="120" width="100" height="8"/>'
        )
    )
    assert not _by_rule(findings, "crowding")


def test_a_label_over_its_field_is_not_crowding():
    """The documented rhythm must not trip the rule that grades it.

    "24px from a label's baseline to its field's baseline" puts a 12px label's
    box at 232-248 and a 16px value's at 252, so the skill's own spacing leaves
    the 4px gap crowding calls a slip -- and an author could only clear it by
    abandoning the rhythm. Neither box was typed: both come from the font-size
    estimate, and the gap is descender space.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<text class="label" x="48" y="244">Delivered</text>'
            '<text data-cds-type="textfield" x="48" y="268" font-size="16"'
            ' data-width="160" data-height="24"'
            ' data-text-var="GVL.Count">%d</text>'
        )
    )
    assert not _by_rule(findings, "crowding")


def test_type_that_actually_collides_is_still_reported():
    """The exemption covers near-misses, not overlaps: two baselines 8px apart
    put one line of type through another, and that is still a finding."""
    findings, _ = lint.lint_svg(
        _svg(
            '<text class="label" x="48" y="244">Delivered</text>'
            '<text class="label" x="48" y="252">Rejected</text>'
        )
    )
    assert _by_rule(findings, "overlap") or _by_rule(findings, "overflow")


def test_findings_name_where_each_element_sits():
    """A pair-wise finding has to say which elements, in the author's own numbers.

    "label #16 overlaps rectangle #27" can only be resolved by counting tags by
    hand, and an author has no tool for that -- one gave up on four overlaps
    after four rounds of restructuring. The coordinates quoted are the ones in
    the file, so a <text> reports its baseline rather than the box top derived
    from it.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<rect class="card" x="24" y="24" width="100" height="100"/>'
            '<text class="label" x="100" y="60" data-width="80">Sticks out</text>'
        )
    )
    message = _by_rule(findings, "overflow")[0].message
    assert 'label #1 "Sticks out" at 100,60' in message
    assert "rectangle #0 at 24,24" in message


def test_circle_radius_is_graded_on_its_diameter():
    """--fix must not resize a shape to fix an alignment problem it does not have.

    r=6 draws a 12px dot, and 12 is on the 4px grid; snapping the radius itself
    inflated it to 16px. A <rect> corner radius is already exempt for the same
    reason.
    """
    clean, _ = lint.lint_svg(_svg('<circle class="ok" cx="100" cy="200" r="6"/>'))
    assert not _by_rule(clean, "grid")

    findings, _ = lint.lint_svg(_svg('<circle class="ok" cx="100" cy="200" r="5"/>'))
    assert _by_rule(findings, "grid")[0].fixes == {"r": "4"}


def test_unsupported_text_anchor_is_reported():
    """Anything but start/middle/end used to be read as start, silently."""
    findings, _ = lint.lint_svg(
        _svg('<text class="label" x="40" y="60" text-anchor="inherit">Hi</text>')
    )
    assert 'text-anchor="inherit"' in _by_rule(findings, "text-anchor")[0].message


def test_anchored_text_without_a_box_is_reported():
    """Centre and right alignment place the glyphs relative to the box width.

    With no data-width that width is estimated from the text, so the alignment
    lands wherever the estimate falls -- and the author sees the preview put
    their label somewhere they did not.
    """
    guessed, _ = lint.lint_svg(
        _svg('<text class="label" x="400" y="164" text-anchor="middle">Hi</text>')
    )
    assert _by_rule(guessed, "text-anchor")

    explicit, _ = lint.lint_svg(
        _svg(
            '<text class="label" x="400" y="164" data-width="80"'
            ' text-anchor="middle">Hi</text>'
        )
    )
    assert not _by_rule(explicit, "text-anchor")


def test_a_field_without_a_box_is_reported():
    """A label can be measured from its own text; a field cannot.

    ``%d`` is three characters wide in the file and four digits wide on the
    screen, so an estimated box fits the format string and clips the value.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<text data-cds-type="textfield" x="48" y="268" font-size="16"'
            ' data-text-var="GVL.Count">%d</text>'
        )
    )
    assert _by_rule(findings, "unsized-field")


def test_a_sized_field_is_not_reported():
    findings, _ = lint.lint_svg(
        _svg(
            '<text data-cds-type="textfield" x="48" y="268" font-size="16"'
            ' data-width="160" data-height="24"'
            ' data-text-var="GVL.Count">%d</text>'
        )
    )
    assert not _by_rule(findings, "unsized-field")


def test_empty_panel_is_reported():
    """Emptiness has to cost something, or the cheapest clean report is a blank one.

    Overlap and crowding both reward taking things out; one author cleared a
    P&ID's findings by deleting every annotation on it. Without this rule the
    linter's own gradient points at an empty screen.
    """
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="24" y="88" width="368" height="296"/>')
    )
    assert "panel at 24,88" in _by_rule(findings, "empty-panel")[0].message


def test_a_card_on_the_screen_background_is_reported():
    """The one shape an author draws and then cannot see.

    ``card`` is a step in from ``panel``, which puts it within 3% of the screen
    background in the light palette. Inside a panel that is the intent; on the
    background it renders as nothing, and the report it produced was "panel and
    card are the same colour" -- from a screen where one box had disappeared.
    """
    findings, _ = lint.lint_svg(
        _svg('<rect class="card" x="24" y="88" width="368" height="120"/>'
             '<text class="label" x="40" y="120">Flow</text>')
    )
    assert "card at 24,88" in _by_rule(findings, "lonely-card")[0].message


def test_a_card_inside_a_panel_is_not_reported():
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="24" y="88" width="368" height="296"/>'
             '<rect class="card" x="40" y="104" width="336" height="96"/>'
             '<text class="label" x="56" y="136">Flow</text>')
    )
    assert not _by_rule(findings, "lonely-card")


def test_a_card_is_not_reported_where_the_palette_separates_it():
    """The rule reads the resolved palette instead of assuming the light one.

    In the dark scheme a card is visibly lighter than the screen, so the shape
    is doing exactly what it says -- and a warning there would be the linter
    disagreeing with what is on screen.
    """
    findings, _ = lint.lint_svg(
        _svg('<rect class="card" x="24" y="88" width="368" height="120"/>'
             '<text class="label" x="40" y="120">Flow</text>'),
        scheme="dark",
    )
    assert not _by_rule(findings, "lonely-card")


def test_content_flush_with_its_container_edge_is_reported():
    """A field ending exactly on the card's edge renders as clipped.

    It is not an overlap -- the field is properly inside the card, which is why
    every other rule passes it -- and the skill asks for 16px of padding and
    said lint grades against it. Five screens came back "Sketch OK" with a row
    of lamps sitting on the panel border.
    """
    findings, _ = lint.lint_svg(
        _svg('<rect class="card" x="40" y="136" width="344" height="72"/>'
             '<text data-cds-type="textfield" x="200" y="192" data-width="168"'
             ' data-height="28" data-text-var="GVL.x">%d</text>')
    )
    message = _by_rule(findings, "padding")[0].message
    assert "0px from the bottom edge of the card at 40,136" in message


def test_padding_is_measured_against_the_innermost_container():
    """A card inside a panel shares its edge; that is one problem, not two."""
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="24" y="88" width="376" height="296"/>'
             '<rect class="card" x="40" y="312" width="344" height="72"/>'
             '<text data-cds-type="textfield" x="200" y="368" data-width="168"'
             ' data-height="28" data-text-var="GVL.x">%d</text>')
    )
    padding = _by_rule(findings, "padding")
    assert len(padding) == 1
    assert "card at 40,312" in padding[0].message


def test_an_accent_bar_flush_inside_its_card_is_not_reported():
    """``cts visu new`` draws it flush on purpose; only content is measured."""
    findings, _ = lint.lint_svg(
        _svg('<rect class="card" x="40" y="136" width="344" height="72"/>'
             '<rect class="ok" x="40" y="136" width="8" height="72"/>'
             '<text class="label" x="72" y="168">Light</text>')
    )
    assert not _by_rule(findings, "padding")


def test_content_with_the_documented_padding_is_not_reported():
    findings, _ = lint.lint_svg(
        _svg('<rect class="panel" x="24" y="88" width="368" height="296"/>'
             '<text class="label" x="40" y="120">Flow</text>')
    )
    assert not _by_rule(findings, "padding")


def test_a_caption_asserting_a_live_state_is_reported():
    """"E-Stop = Stopped" is a reading, and it is baked into a Text ID.

    Three screens in a row shipped one. It passes every geometric rule, it is
    the most declarative thing on the screen, and it says "Stopped" while the
    machine runs -- which is the one class of defect on an HMI that is worse
    than an ugly layout.
    """
    findings, _ = lint.lint_svg(
        _svg('<text class="label" x="616" y="432">E-Stop = Stopped</text>')
    )
    hits = _by_rule(findings, "static-state")
    assert len(hits) == 1
    assert hits[0].severity == "warn"
    assert '"Stopped"' in hits[0].message
    assert "data-text-var" in hits[0].message


def test_a_claim_after_a_dash_is_reported():
    """The separator is not always "="; the second screen used an em dash."""
    findings, _ = lint.lint_svg(
        _svg(u'<text class="label" x="500" y="432">'
             u'9 sensors — diagnostics active</text>')
    )
    assert '"diagnostics active"' in _by_rule(findings, "static-state")[0].message


def test_a_lamp_legend_is_not_mistaken_for_a_reading():
    """"Running" beside a lamp is the label the screen needs, not a claim.

    This is the rule's whole risk: state words belong on a well-labelled
    screen, and matching one anywhere in a caption would fire on every legend
    written correctly -- including the two the scaffold ships with.
    """
    findings, _ = lint.lint_svg(
        _svg('<text class="label" x="72" y="168">Running</text>'
             '<text class="label" x="72" y="200">Motor Running</text>'
             '<text class="label" x="72" y="232">Fault</text>'
             '<text class="label" x="72" y="264">E-Stop</text>')
    )
    assert not _by_rule(findings, "static-state")


def test_a_label_waiting_for_its_field_is_not_reported():
    """A trailing separator with nothing after it is a caption, not a value."""
    findings, _ = lint.lint_svg(
        _svg('<text class="label" x="72" y="168">Line speed:</text>')
    )
    assert not _by_rule(findings, "static-state")


def test_a_bound_field_may_say_what_it_likes():
    """With data-text-var the text is a format string; the value is live."""
    findings, _ = lint.lint_svg(
        _svg('<text data-cds-type="textfield" x="200" y="192" data-width="168"'
             ' data-height="28" data-text-var="GVL.sState">Status: Running</text>')
    )
    assert not _by_rule(findings, "static-state")


def test_untouched_scaffold_is_not_called_clean():
    """The starter screen is the one screen guaranteed not to be finished.

    It passes every geometric rule -- it is laid out correctly -- so lint used to
    answer "no design problems found" to a screen showing a process nobody runs,
    bound to variables nobody declared. Ten authors were set the same task and
    one shipped exactly that.
    """
    findings, _ = lint.lint_svg(commands.compose_skeleton(800, 480, "Test Screen"))
    scaffold = _by_rule(findings, "scaffold")
    assert len(scaffold) == 1
    assert scaffold[0].severity == "info"
    assert not scaffold[0].fixable


# ---------------------------------------------------------------------------
# --fix
# ---------------------------------------------------------------------------


def test_apply_fixes_rewrites_only_the_flagged_attributes():
    svg = _svg(
        "\n  <!-- a comment that must survive -->\n"
        '  <rect class="panel" x="23" y="89" width="367" height="295"/>\n'
        '  <text class="label" x="40" y="124">In here</text>\n'
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


def test_fix_iterates_until_the_sketch_stops_changing(tmp_path, capsys):
    """One pass is not enough, because two fixable rules feed each other.

    The font-scale rule rewrites font-size, and a <text> baseline is graded
    through its box top -- which is the baseline minus that very font size. So
    the grid fix computed in the same pass was measured against the *old* size,
    and an author who ran --fix once was handed a file the next lint still
    complained about. Here 18px snaps to 16, which moves the box top, which
    moves the baseline again on the following pass.
    """
    svg_path = tmp_path / "cascade.svg"
    svg_path.write_text(
        _svg('<text class="label" x="24" y="300" font-size="18">Speed</text>'),
        encoding="utf-8",
    )

    commands.lint_svg(None, str(svg_path), "", None, fix=True)

    out = capsys.readouterr().err
    assert "Sketch OK" in out
    assert "two rules are disagreeing" not in out
    # And the file on disk is what a second run would have to agree with.
    findings, _ = lint.lint_svg(svg_path.read_text(encoding="utf-8"))
    assert findings == [], [f.message for f in findings]


def test_control_on_the_wrong_tag_is_reported():
    """A circle is the natural shape for a lamp, and it silently is not one.

    parse_svg promotes on the (tag, data-cds-type) pair, so a control attribute
    anywhere else never matches: the element falls through to the plain shape
    parser and data-var goes on the floor. It draws, it used to lint clean, and
    it sits at one colour forever.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<circle class="ok" cx="48" cy="152" r="8" data-cds-type="lamp"'
            ' data-color="green" data-var="HMI.Running"/>'
        )
    )
    message = _by_rule(findings, "control-tag")[0].message
    assert "only works on <rect>, not <circle>" in message
    # And it has to name the shape that will actually be drawn. parse_svg files
    # every plain shape under type "rectangle" and keeps the real one in
    # params["shape"], so reporting the type would promise a rectangle where an
    # ellipse appears -- and send the author looking for the wrong element.
    assert "plain ellipse" in message
    assert "rectangle" not in message


def test_findings_name_the_drawn_shape_not_the_parser_category():
    """A round element must never be reported as a rectangle.

    Every message that names an element goes through _shape_of for this reason;
    the margin rule is the cheapest one to provoke.
    """
    findings, _ = lint.lint_svg(_svg('<circle cx="8" cy="160" r="8"/>'))
    assert "ellipse sits within" in _by_rule(findings, "margin")[0].message


@pytest.mark.parametrize(
    "cls,below",
    [("label", 4), ("caption", 5), ("h2", 8), ("h1", 10), ("value", 12)],
)
def test_text_box_hangs_below_the_baseline_by_the_documented_amount(cls, below):
    """SKILL.md quotes these five numbers, so they cannot be left to drift.

    A text box is 1.4x the font size tall (floored at 16, rounded up to the 4px
    grid), and the top is the baseline minus the font size -- so the box extends
    *below* the baseline. Three overlaps in one authoring run came from sizing a
    card to the baseline of the value inside it; the numbers an author needs to
    avoid that are only trustworthy if a test holds them to the code.
    """
    parsed = svg_import.parse_svg(
        _svg('<text class="{0}" x="40" y="160">Xy</text>'.format(cls))
    )
    _x, top, _w, height = lint._geom(parsed["elements"][0]["params"])
    assert top + height - 160 == below


def test_unknown_control_type_is_reported():
    findings, _ = lint.lint_svg(
        _svg('<rect x="24" y="88" width="160" height="48" data-cds-type="gauge"/>')
    )
    assert "unknown" in _by_rule(findings, "control-tag")[0].message


def test_control_on_its_own_tag_is_not_reported():
    findings, _ = lint.lint_svg(
        _svg(
            '<rect data-cds-type="lamp" x="40" y="144" width="20" height="20"'
            ' data-color="green" data-var="HMI.Running"/>'
            '<rect data-cds-type="button" x="24" y="408" width="160" height="48"'
            ' data-text="Go" data-cds-tap="TAP HMI.Go"/>'
            '<text data-cds-type="textfield" x="24" y="172" data-width="200"'
            ' data-height="32" data-text-var="HMI.V" font-size="12">%3.1f</text>'
        )
    )
    assert not _by_rule(findings, "control-tag")


def test_class_on_a_native_control_is_reported_as_inert():
    """Measured, not assumed: a class changes nothing on a field.

    Size, font colour and fill come back byte-identical with class="value",
    class="alarm" or no class at all -- the field takes the CODESYS control
    style and the colour-class system does not reach it. Silent, so the screen
    looks like the class was the wrong one rather than ignored.
    """
    findings, _ = lint.lint_svg(
        _svg(
            '<text data-cds-type="textfield" x="24" y="172" data-width="200"'
            ' data-height="32" data-text-var="H.V" class="value">%3.1f</text>'
        )
    )
    inert = _by_rule(findings, "inert-class")
    assert len(inert) == 1
    assert inert[0].severity == "info"
    assert "font-size" in inert[0].message


def test_a_tag_named_inside_a_comment_does_not_shift_the_index():
    """The index and parse_svg must agree on what element #N is.

    parse_svg does not see comments, so a comment that merely *names* a tag used
    to add a phantom entry to the source index -- and from there every finding
    was attributed to its neighbour, with --fix rewriting the wrong element's
    attributes. Sketches explain themselves in comments and a comment about a
    tag naturally names it, so this was reached by writing an ordinary remark:
    the shipped pid-schematic.svg says "a pipe is a rect, not a <line>" and
    silently mis-indexed every element after it.
    """
    svg = _svg(
        "<!-- a pipe is a thin <rect>, not a <line>: a CODESYS line is 1px -->"
        '<rect class="pipe-water" x="24" y="244" width="80" height="8"/>'
        '<text class="label" x="24" y="300">Suction</text>'
    )
    tags = lint.index_source_tags(svg)
    findings, parsed = lint.lint_svg(svg)
    assert len(tags) == len(parsed["elements"]) == 2
    assert lint._SourceElement(tags[1][2]).tag == "text"

    # And the off-by-one showed up as findings pinned to the wrong element.
    assert findings == [], [f.message for f in findings]


def test_fix_after_a_tag_naming_comment_rewrites_the_right_element(tmp_path):
    """The harm the index drift did: --fix editing an innocent bystander.

    With the phantom entry in place, the off-grid <text> below was reported at
    the index of the <rect> above it, so --fix snapped the rect -- which was
    already on the grid -- and left the text where it was.
    """
    svg = _svg(
        "<!-- draw the run as a <rect>, never a <line> -->"
        '<rect class="pipe-water" x="24" y="244" width="80" height="8"/>'
        '<text class="label" x="24" y="301">Suction</text>'
    )
    findings, _ = lint.lint_svg(svg)
    fixed, count = lint.apply_fixes(svg, findings)

    assert count == 1
    assert 'x="24" y="244" width="80" height="8"' in fixed  # rect untouched
    assert '<text class="label" x="24" y="300">' in fixed  # text moved instead


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

    The one thing lint may say about a fresh scaffold is that it is a fresh
    scaffold: the ``scaffold`` rule is an info, it names work still to do rather
    than a defect, and it is the whole reason lint no longer answers "no design
    problems found" to an untouched starter screen.
    """
    width, height = size
    text = commands.compose_skeleton(width, height, "Test Screen")
    findings, parsed = lint.lint_svg(text)
    assert _rules(findings) in ([], ["scaffold"]), [f.message for f in findings]
    assert all(f.severity == "info" for f in findings)
    assert (parsed["canvas"]["width"], parsed["canvas"]["height"]) == (width, height)


@pytest.mark.parametrize("size", [(320, 240), (240, 180)])
def test_new_warns_when_the_canvas_is_below_the_layout_floor(size, tmp_path, capsys):
    """The skeleton does not degrade below 480x320 -- it collides.

    The header band, the panel inset and the action row are fixed costs, so past
    a point there is nothing left to drop and the blocks land on each other: at
    240x180 the composition puts labels on top of buttons and computes a text box
    of negative width. Handing that back with an [OK] and no other comment reads
    as the sketch format being broken rather than the canvas being out of range.
    """
    width, height = size
    commands.new_svg(str(tmp_path / "s.svg"), "S", width, height)
    err = capsys.readouterr().err
    assert "below 480x320" in err

    findings, _ = lint.lint_svg(commands.compose_skeleton(width, height, "S"))
    assert [f for f in findings if f.severity == "warn"], (
        "the warning is only worth printing while the skeleton really does "
        "come out broken at this size"
    )


def test_new_warns_when_the_canvas_is_not_a_multiple_of_four():
    """An odd canvas puts the layout's own halves off the grid it enforces."""
    findings, _ = lint.lint_svg(commands.compose_skeleton(803, 481, "S"))
    assert _by_rule(findings, "grid")


def test_new_is_quiet_at_the_sizes_it_is_tested_at(tmp_path, capsys):
    commands.new_svg(str(tmp_path / "s.svg"), "S", 800, 480)
    err = capsys.readouterr().err
    assert "[WARN]" not in err, err


def test_composed_skeleton_comment_is_well_formed_xml():
    """``--`` is illegal inside an XML comment, and the guidance block is large.

    Naming a flag in the sketch's own comment (``cts visu lint --fix``) makes
    the whole file unparseable, and the failure surfaces as a ParseError on
    line 5 rather than as anything about comments.
    """
    text = commands.compose_skeleton(800, 480, "Test Screen")
    for comment in re.findall(r"<!--(.*?)-->", text, re.DOTALL):
        assert "--" not in comment


_SKILL = os.path.join(_ROOT, "skills", "cds-visu-svg", "SKILL.md")


def test_skill_md_examples_lint_clean():
    """SKILL.md says its own example "Lints clean" -- nothing checked that.

    An authoring model reads this file and imitates the sketch at the bottom of
    it, so a defect there is a defect in every screen written from the skill.
    The baselines are the part that rots: they are deliberately not multiples of
    4 (an .h1 sits at y=46, not 48) and a well-meaning tidy-up to "fix" them
    would break the grid rule the same file documents.
    """
    with open(_SKILL, "r", encoding="utf-8") as handle:
        text = handle.read()
    blocks = re.findall(r"```xml\n(<svg\b.*?)```", text, re.DOTALL)
    assert blocks, "no full-sketch example found in SKILL.md"
    for block in blocks:
        findings, _ = lint.lint_svg(block)
        assert findings == [], [f.message for f in findings]


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

# -*- coding: utf-8 -*-
"""Tests for the locked-field hover rule behind the options dialog.

Windows raises no mouse events for a disabled control, so a tooltip set on one
never opens; the dialog's group boxes hit-test their disabled children
themselves. ``locked_hover_reason`` is that hit test, kept free of WinForms so
it can be checked here.
"""

import os
import sys



_IDE_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "products",
        "codesys-host",
        "src",
        "ide_bridge",
    )
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

import codesys_ui


LAYOUT_HINT = "locked after the first export"
MODE_HINT = "mode is fixed"


def _child(left, top, width, height, enabled, reason):
    return ((left, top, width, height), enabled, reason)


def test_a_disabled_child_under_the_point_answers():
    children = [_child(10, 20, 100, 20, False, LAYOUT_HINT)]
    assert codesys_ui.locked_hover_reason(children, (50, 25)) == LAYOUT_HINT


def test_an_enabled_child_is_skipped():
    # It opens its own tooltip, so the group must not speak over it.
    children = [_child(10, 20, 100, 20, True, LAYOUT_HINT)]
    assert codesys_ui.locked_hover_reason(children, (50, 25)) is None


def test_empty_space_answers_nothing():
    children = [_child(10, 20, 100, 20, False, LAYOUT_HINT)]
    assert codesys_ui.locked_hover_reason(children, (5, 5)) is None
    assert codesys_ui.locked_hover_reason(children, (200, 100)) is None


def test_a_disabled_child_without_a_reason_is_skipped():
    children = [_child(10, 20, 100, 20, False, None),
                _child(10, 20, 100, 20, False, "")]
    assert codesys_ui.locked_hover_reason(children, (50, 25)) is None


def test_the_first_match_in_the_list_wins():
    children = [
        _child(10, 20, 100, 20, False, "front"),
        _child(10, 20, 100, 20, False, "back"),
    ]
    assert codesys_ui.locked_hover_reason(children, (50, 25)) == "front"


def test_a_later_child_answers_where_no_earlier_one_matches():
    children = [
        _child(10, 20, 40, 20, False, "left"),
        _child(60, 20, 40, 20, False, "right"),
    ]
    assert codesys_ui.locked_hover_reason(children, (70, 25)) == "right"
    assert codesys_ui.locked_hover_reason(children, (30, 25)) == "left"


def test_the_edges_belong_to_the_child():
    children = [_child(10, 20, 100, 20, False, LAYOUT_HINT)]
    assert codesys_ui.locked_hover_reason(children, (10, 20)) == LAYOUT_HINT
    assert codesys_ui.locked_hover_reason(children, (109, 39)) == LAYOUT_HINT
    # One past the right edge and one past the bottom are outside.
    assert codesys_ui.locked_hover_reason(children, (110, 39)) is None
    assert codesys_ui.locked_hover_reason(children, (109, 40)) is None
    # One before the top-left corner is outside too.
    assert codesys_ui.locked_hover_reason(children, (9, 19)) is None


def test_a_reason_is_returned_even_when_a_reasonless_child_overlaps():
    children = [
        _child(10, 20, 100, 20, False, None),
        _child(10, 20, 100, 20, False, MODE_HINT),
    ]
    assert codesys_ui.locked_hover_reason(children, (50, 25)) == MODE_HINT


def test_no_children_answer_nothing():
    assert codesys_ui.locked_hover_reason([], (10, 10)) is None
    assert codesys_ui.locked_hover_reason(None, (10, 10)) is None

# -*- coding: utf-8 -*-
"""
test_cli_text_output.py — `--pretty` has to stay readable and bounded.

The old renderer guarded on item count and never on size, which broke in both
directions at once:

  * five added objects carrying a ~300 KB XML blob each fell under the "more
    than 5 items" threshold and were printed in full — `cts --pretty compare`
    emitted 1.5 MB across 16 lines;
  * anything longer than five items collapsed to "[N items]", so a whole
    project tree rendered as "children: [8 items]" and `read-log` as
    "messages: [15 items]".

One extra object in the project flipped a payload between those two, so output
size tracked item count rather than content.
"""

from __future__ import annotations

import json

import pytest

from cds_text_sync._cli_io import (
    MAX_TEXT_LINES,
    MAX_TEXT_VALUE_CHARS,
    _format_output,
)


def _lines(rendered):
    """Physical lines — what the terminal actually shows."""
    return rendered.split("\n")


# ---------------------------------------------------------------------------
# The regression
# ---------------------------------------------------------------------------


def test_a_few_huge_items_stay_bounded():
    """The exact shape that produced 1.5 MB: 5 items, ~300 KB each."""
    payload = {
        "objects": {
            "added": [
                {
                    "name": f"T_Screen{i}",
                    "disk_content": "<Single>" + ("x" * 300_000) + "</Single>",
                }
                for i in range(5)
            ]
        },
        "summary": {"added": 5, "modified": 0},
    }
    rendered = _format_output(payload, "text", "sync_compare_text")

    assert len(rendered) < 20_000, "text mode is dumping payloads again"
    assert len(_lines(rendered)) <= MAX_TEXT_LINES + 1
    # Still informative: names survive, only the blob is cut.
    assert "T_Screen0" in rendered
    assert "more chars" in rendered


def test_output_size_does_not_track_item_count():
    """Six items must not render smaller than five — that was the old cliff."""
    def payload(count):
        return {"added": [{"name": f"obj{i}", "body": "y" * 50_000}
                          for i in range(count)]}

    five = len(_format_output(payload(5), "text"))
    six = len(_format_output(payload(6), "text"))
    assert six >= five


def test_long_lists_are_shown_not_hidden():
    """read-log used to render as a bare 'messages: [15 items]'."""
    payload = {"messages": [f"message {i}" for i in range(15)], "count": 15}
    rendered = _format_output(payload, "text", "read_log")

    assert "[15 items]" not in rendered
    assert "message 0" in rendered
    assert "message 14" in rendered


def test_nested_structures_are_walked():
    """project-tree used to render as a bare 'children: [8 items]'."""
    payload = {
        "name": "Device",
        "children": [
            {"name": "PLC Logic", "children": [{"name": "Application"}]},
            {"name": "HMI", "children": [{"name": "T_Overview"}]},
        ],
    }
    rendered = _format_output(payload, "text", "project_tree")

    for expected in ("PLC Logic", "Application", "HMI", "T_Overview"):
        assert expected in rendered, expected


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_embedded_newlines_cannot_break_the_budget():
    """A scalar full of newlines would otherwise outrun a per-entry budget."""
    payload = {"content": "\n".join(f"line {i}" for i in range(10_000))}
    rendered = _format_output(payload, "text")

    lines = _lines(rendered)
    assert lines[0].startswith("content: "), "the scalar must stay on one line"
    assert len(lines) == 2, "one entry, then the shortened-output footer"
    assert len(rendered) <= MAX_TEXT_VALUE_CHARS + 200


def test_a_deep_tree_stays_within_the_budget():
    node = {"name": "leaf"}
    for depth in range(40):
        node = {"name": f"level{depth}", "children": [node, node, node]}

    rendered = _format_output(node, "text", "project_tree")
    assert len(_lines(rendered)) <= MAX_TEXT_LINES + 1


def test_truncation_points_at_the_complete_output():
    payload = {"items": [{"n": i, "v": "z" * 100} for i in range(500)]}
    rendered = _format_output(payload, "text")

    assert "--output json" in rendered


# ---------------------------------------------------------------------------
# Nothing else moved
# ---------------------------------------------------------------------------


def test_flat_dicts_render_exactly_as_before():
    """`cts where`, `ping` and `permissions` are all flat — keep them stable."""
    payload = {"Body": "C:\\Workspace", "Valid": True, "Layout": "split"}
    assert _format_output(payload, "text") == (
        "Body: C:\\Workspace\nValid: True\nLayout: split"
    )


def test_the_title_header_is_unchanged():
    assert _format_output({"a": 1}, "text", "ping").startswith("── ping ──\n")


def test_nested_dicts_and_short_lists_render_as_before():
    payload = {"plc": {"online": None}, "tags": ["a", "b"]}
    assert _format_output(payload, "text") == (
        "plc:\n  online: None\ntags:\n  - a\n  - b"
    )


@pytest.mark.parametrize(
    "payload,expected",
    [({"x": []}, "x: []"), ({"x": {}}, "x: {}"), ({}, "{}")],
)
def test_empty_containers(payload, expected):
    assert _format_output(payload, "text") == expected


def test_empty_scalars_leave_no_trailing_space():
    assert _format_output({"ide_content": ""}, "text") == "ide_content:"


def test_json_mode_is_untouched():
    payload = {"objects": {"added": [{"body": "x" * 400_000}]}, "n": 1}
    rendered = _format_output(payload, "json")

    assert json.loads(rendered) == payload, "json must stay complete and exact"


def test_none_renders_as_before():
    assert _format_output(None, "text") == "None"

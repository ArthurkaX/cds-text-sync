# -*- coding: utf-8 -*-
"""A message box in the IDE stays on the screen: its text is cut to fit."""

import os
import sys

_IDE_BRIDGE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "products", "codesys-host", "src", "ide_bridge")
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

from ide_run_action import _fit_dialog  # noqa: E402


def test_a_long_message_is_cut_to_lines_and_line_length():
    message = "\n".join(["line {0} ".format(i) + "x" * 500 for i in range(40)])

    shown = _fit_dialog(message).split("\n")

    assert len(shown) == 26
    assert shown[-1] == "... 15 more line(s) in the sync log."
    assert all(len(line) <= 304 for line in shown)


def test_a_short_message_is_shown_as_it_is():
    assert _fit_dialog("Import done.\nNo changes.") == "Import done.\nNo changes."

# -*- coding: utf-8 -*-
"""
test_build_severity.py — one severity classifier for the daemon and the CLI.

The daemon counts error and warning messages by substring ("Error" in
severity) and the CLI turns the same list into problems the same way; both
read a string CODESYS controls.  If a lowercased or qualified spelling slips
past one side, a compile failure reads as a clean build there and not here,
so the classification itself is pinned here.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _extra in (ROOT / "shared" / "src", ROOT / "products" / "codesys-host" / "src" / "ide_bridge"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from cts_shared.build_severity import (  # noqa: E402
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    severity_kind,
)


@pytest.mark.parametrize(
    "value",
    ["Error", "error", "ERROR", " error ", "Compile Error", "Error:"],
)
def test_every_error_spelling_is_an_error(value):
    assert severity_kind(value) == SEVERITY_ERROR


@pytest.mark.parametrize("value", ["Warning", "warning", "WARNING", "Compile Warning"])
def test_every_warning_spelling_is_a_warning(value):
    assert severity_kind(value) == SEVERITY_WARNING


@pytest.mark.parametrize("value", ["Information", "info", "INFO"])
def test_information_is_information(value):
    assert severity_kind(value) == SEVERITY_INFO


def test_an_error_outranks_the_warning_in_its_own_text():
    # "Compile Error" also contains no "warning", but the reverse spelling is
    # the trap: a message qualified as both must count once, as the error.
    assert severity_kind("Error (Warning)") == SEVERITY_ERROR


@pytest.mark.parametrize("value", ["", "   ", None, "Message", "Note", 7, []])
def test_an_unrecognised_severity_is_neither(value):
    assert severity_kind(value) == ""

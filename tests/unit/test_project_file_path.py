# -*- coding: utf-8 -*-
"""
test_project_file_path.py — Regression guard for relative cds-sync-folder anchoring.

Root cause of GH #61: IronPython attribute access is case-sensitive and the
canonical CODESYS ScriptEngine attribute is the lowercase ``path``. Older call
sites tried only ["filename", "FileName", "FullName", "Path"], so on builds such
as SP18 (which expose the path only via lowercase ``path``) the relative sync
folder was never anchored and fell through to a misleading "Access denied".

``_project_file_path`` centralizes the case-insensitive lookup with lowercase
``path`` tried FIRST. These tests pin that contract.
"""

import os
import sys

_IDE_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

import ide_daemon_state as state


class _LowerPathProject(object):
    """The SP18 shape: exposes ONLY lowercase ``path`` (the #61 regression)."""

    path = r"C:\Users\eddie\Desktop\Test\Untitled1.project"


class _PascalCaseProject(object):
    """Older/other builds: no lowercase ``path``, only PascalCase variants."""

    FullName = r"D:\projects\Sample.project"


class _NoPathProject(object):
    """Unsaved / path-less project: nothing usable."""

    pass


class _RaisingProject(object):
    """Attribute access raises — must be swallowed, not propagated."""

    @property
    def path(self):
        raise RuntimeError("no path on this build")

    filename = r"E:\fallback\Fallback.project"


def test_lowercase_path_is_resolved():
    # The exact SP18 regression from GH #61.
    assert (
        state._project_file_path(_LowerPathProject())
        == r"C:\Users\eddie\Desktop\Test\Untitled1.project"
    )


def test_pascalcase_fallback_still_works():
    assert state._project_file_path(_PascalCaseProject()) == r"D:\projects\Sample.project"


def test_missing_path_returns_empty_string():
    # Empty (not None) so os.path.dirname("") is "" and callers can loud-fail.
    assert state._project_file_path(_NoPathProject()) == ""


def test_raising_attribute_falls_through():
    assert state._project_file_path(_RaisingProject()) == r"E:\fallback\Fallback.project"

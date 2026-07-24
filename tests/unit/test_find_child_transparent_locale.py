# -*- coding: utf-8 -*-
"""
test_find_child_transparent_locale.py -- Locale-tolerant container resolution.

_find_child_transparent must resolve a (possibly localized) path segment against
the live IDE tree regardless of whether the IDE reports English or localized
object names, and must keep the transparent "Plc Logic" hop working in both
locales -- while leaving English resolution behaviorally identical.

ide_apply_patch drags in IDE-side imports; skip cleanly if it cannot import
under CPython (it still runs live under IronPython inside the IDE).
"""

import os
import sys

import pytest

_BRIDGE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "ide_bridge")
)
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

try:
    from ide_apply_patch import _find_child_transparent
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(
        "ide_apply_patch not importable under CPython: %s" % exc,
        allow_module_level=True,
    )


class FakeObj(object):
    def __init__(self, name, children=None):
        self._name = name
        self._children = children or []

    def get_name(self):
        return self._name

    def get_children(self):
        return self._children


def _spine(plc_label):
    """Device -> <plc_label> -> Application -> FB_Test."""
    fb = FakeObj("FB_Test")
    app = FakeObj("Application", [fb])
    plc = FakeObj(plc_label, [app])
    device = FakeObj("Device", [plc])
    return device, plc, app, fb


def test_localized_segment_matches_english_ide_name():
    # Stored (localized) segment resolves against the English live object name.
    device, plc, _app, _fb = _spine("Plc Logic")
    assert _find_child_transparent(device, u"PLC逻辑") is plc


def test_english_resolution_is_unchanged():
    device, plc, app, _fb = _spine("Plc Logic")
    assert _find_child_transparent(device, "Plc Logic") is plc
    # Transparent hop: Application is a grandchild through Plc Logic.
    assert _find_child_transparent(device, "Application") is app
    assert _find_child_transparent(device, "Missing") is None


def test_transparent_hop_survives_localized_plc_logic_in_live_tree():
    # Even if the IDE itself reports a localized "Plc Logic", the hop still works.
    device, _plc, app, _fb = _spine(u"PLC逻辑")
    assert _find_child_transparent(device, "Application") is app

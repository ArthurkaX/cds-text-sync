# -*- coding: utf-8 -*-
"""
test_ide_time.py — response timestamps carry a zone, one format, one place.

Live, ``tree_built_at`` read ``09:44`` while the host clock said ``20:45``: the
daemon formatted a local time with no zone, so the two clocks disagreed about
what the string meant. Every timestamp a daemon response carries is now
ISO-8601 UTC with a trailing ``Z`` through ``ide_time.iso_utc``. A test also
scans the producers so a new field cannot quietly reintroduce the ambiguous
format.
"""

from __future__ import print_function

import calendar
import importlib
import os
import sys

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

# The format the fix replaced: ISO-looking but with no zone marker.
_AMBIGUOUS = "%Y-%m-%dT%H:%M:%S"

# Response-producing modules that used to format their own timestamps.
_PRODUCERS = [
    "ide_handlers_sync.py",
    "ide_last_result.py",
    "ide_handlers_crc.py",
    "ide_reverse_pipe_loop.py",
    "project_snapshooter.py",
]


def _time_module():
    return importlib.import_module("ide_time")


# ── the one format ─────────────────────────────────────────────────────────


def test_iso_utc_is_utc_with_a_z_suffix():
    iso_utc = _time_module().iso_utc
    assert iso_utc(0) == "1970-01-01T00:00:00Z"
    assert iso_utc().endswith("Z")


def test_iso_utc_does_not_depend_on_the_local_zone():
    """The live bug: the same instant had to mean one thing everywhere."""
    iso_utc = _time_module().iso_utc
    epoch = calendar.timegm((2026, 10, 5, 20, 45, 12, 0, 0, 0))
    assert iso_utc(epoch) == "2026-10-05T20:45:12Z"


def test_tree_built_at_is_utc():
    snapshooter = importlib.import_module("project_snapshooter")
    path = os.path.join(_BRIDGE, "ide_time.py")
    snapshooter._set_last_tree_build("rebuilt", path)
    info = snapshooter.tree_build_info()
    assert info["built_at"].endswith("Z")
    assert info["source"] == "rebuilt"


# ── the producers no longer format their own ambiguous stamps ──────────────


def test_no_producer_formats_a_zoneless_iso_stamp():
    for name in _PRODUCERS:
        source = open(os.path.join(_BRIDGE, name), encoding="utf-8").read()
        assert _AMBIGUOUS not in source, name
        assert "ide_time" in source, name

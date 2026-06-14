# -*- coding: utf-8 -*-
"""
Project_snapshooter.py - CODESYS entrypoint for PLC variable presets.

Usage in CODESYS scripting:

    import Project_snapshooter as snapshooter
    data = snapshooter.take(paths=["GVL_Routing.partCount"], label="speed")
    report = snapshooter.restore(data, apply=False)

Run the script directly to start the small interactive wizard.
"""

from __future__ import print_function

import os
import sys


_ROOT = os.path.dirname(os.path.abspath(__file__))
_BRIDGE = os.path.join(_ROOT, "src", "ide_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

try:
    import imp
    _impl = imp.load_source(
        "project_snapshooter",
        os.path.join(_BRIDGE, "project_snapshooter.pyw"),
    )
except Exception:
    import project_snapshooter as _impl  # noqa: E402

FORMAT_VERSION = _impl.FORMAT_VERSION
build_tree = _impl.build_tree
build_tui_tree = _impl.build_tui_tree
compare = _impl.compare
interactive = _impl.interactive
load = _impl.load
load_preset = _impl.load_preset
read_values = _impl.read_values
restore = _impl.restore
restore_preset = _impl.restore_preset
save = _impl.save
save_preset = _impl.save_preset
snapshooter = _impl.snapshooter
take = _impl.take


if __name__ == "__main__":
    interactive()

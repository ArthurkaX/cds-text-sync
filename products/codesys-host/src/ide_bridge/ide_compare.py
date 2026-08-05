# -*- coding: utf-8 -*-
"""
ide_compare.py - Compare current IDE snapshot with disk state and report differences.
Must be compatible with IronPython 2.7.
"""
from __future__ import print_function

import ide_run_action


def compare_project(system, project, project_root, dump_root=None, include_objects=False, view_root=None, layout_mode=None):
    """
    Exports the current IDE state into a compare-only snapshot, then compares
    it against the exported views on disk.
    """
    return ide_run_action.run_action(
        "compare",
        system,
        project,
        project_root,
        dump_root=dump_root,
        view_root=view_root,
        layout_mode=layout_mode,
        include_objects=include_objects,
    )

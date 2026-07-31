# -*- coding: utf-8 -*-
"""
codesys_compare_operation.py - Delegating compare workflow.
Uses the XML-first bridge to produce a compare report.
"""
from __future__ import print_function

from codesys_runtime import run_bridge_operation


def main(params=None, runtime=None):
    def invoke(system, project, base_dir, view_root, layout_mode):
        import ide_compare
        return ide_compare.compare_project(
            system,
            project,
            base_dir,
            view_root=view_root,
            layout_mode=layout_mode,
        )

    return run_bridge_operation(
        params,
        runtime,
        globals(),
        "compare",
        invoke,
        "Compare failed. Check logs in the external engine.",
    )

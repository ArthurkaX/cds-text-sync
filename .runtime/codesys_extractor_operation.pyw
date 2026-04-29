# -*- coding: utf-8 -*-
"""
codesys_extractor_operation.pyw - Delegating extract workflow.
Now delegates to the new ide_bridge and external engine architecture.
"""
from __future__ import print_function

from codesys_runtime import run_bridge_operation

def main(params=None, runtime=None):
    def invoke(system, project, base_dir, view_root, layout_mode):
        import ide_run_action
        return ide_run_action.run_action(
            "export",
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
        "export",
        invoke,
        "Extraction failed. Check logs in the external engine.",
    )

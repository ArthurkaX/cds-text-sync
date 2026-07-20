# -*- coding: utf-8 -*-
"""
codesys_extractor_operation.pyw - Delegating extract workflow.
Now delegates to the new ide_bridge and external engine architecture.
"""
from __future__ import print_function

from codesys_runtime import resolve_runtime, run_bridge_operation

def main(params=None, runtime=None):
    params = params or {}

    def invoke(system, project, base_dir, view_root, layout_mode):
        import ide_run_action
        active_runtime = resolve_runtime(
            runtime, caller_globals=globals(), params=params
        )
        confirm_overwrite_fn = None
        if not active_runtime.is_headless and hasattr(
            active_runtime.ui, "confirm_overwrite_dirty"
        ):
            confirm_overwrite_fn = active_runtime.ui.confirm_overwrite_dirty
        return ide_run_action.run_action(
            "export",
            system,
            project,
            base_dir,
            view_root=view_root,
            layout_mode=layout_mode,
            overwrite_dirty=params.get("overwrite_dirty"),
            remove_orphans=params.get("remove_orphans"),
            confirm_overwrite_fn=confirm_overwrite_fn,
        )

    return run_bridge_operation(
        params,
        runtime,
        globals(),
        "export",
        invoke,
        "Extraction failed. Check logs in the external engine.",
    )

# -*- coding: utf-8 -*-
"""
codesys_resources_operation.py - Snapshot-based resource diagnostics workflow.
"""
from __future__ import print_function
import os
import sys

from codesys_runtime import resolve_runtime
from codesys_utils import load_base_dir, init_logging, resolve_projects


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}

    init_logging(base_dir)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    utility_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bridge_dir = os.path.join(utility_root, "src", "ide_bridge")
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)

    try:
        import ide_resources
        success = ide_resources.analyze_resources(
            runtime.system,
            projects_obj.primary,
            base_dir,
            view_root=params.get("view_root"),
            layout_mode=params.get("layout"),
            limit=params.get("limit"),
        )
        if success:
            runtime.ui.info("Resource analysis completed successfully.")
            return {"status": "success"}
        runtime.ui.error("Resource analysis failed.")
        return {"status": "error"}
    except Exception as error:
        runtime.ui.error("Error invoking resources analysis: " + str(error))
        return {"status": "error", "error": str(error)}

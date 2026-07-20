# -*- coding: utf-8 -*-
"""
codesys_compare_ui_operation.pyw - Interactive compare workflow.
Runs XML-first compare, shows an object list, then optionally starts import/export.
"""
from __future__ import print_function
import json
import os
import sys

from codesys_runtime import resolve_runtime
from codesys_utils import load_base_dir, init_logging, resolve_projects


def _object_items(report, key):
    objects = report.get("objects", {})
    if key in objects:
        return objects.get(key) or []
    details = report.get("details", {})
    return [
        {
            "guid": guid,
            "name": guid,
            "type_guid": "",
            "path": "",
            "view_path": "",
        }
        for guid in details.get(key, [])
    ]


def _load_report(report_path):
    with open(report_path, "r") as handle:
        return json.load(handle)


def _selected_guids(selected, normalize_guid):
    guids = []
    seen = {}
    for item in selected or []:
        guid = ""
        try:
            guid = item.get("guid") or ""
        except Exception:
            guid = ""
        guid = normalize_guid(guid)
        if guid and guid not in seen:
            seen[guid] = True
            guids.append(guid)
    return guids


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

    system = runtime.system
    project = projects_obj.primary

    utility_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bridge_dir = os.path.join(utility_root, "src", "ide_bridge")
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)

    try:
        import ide_compare
        import ide_run_action
        import ide_runtime_common

        project_layout = ide_runtime_common.layout(
            base_dir,
            view_root=params.get("view_root"),
            layout_mode=params.get("layout"),
        )
        report_path = os.path.join(project_layout.dump_root, "compare_report.json")

        success = ide_compare.compare_project(
            system,
            project,
            base_dir,
            include_objects=True,
            view_root=params.get("view_root"),
            layout_mode=params.get("layout"),
        )
        if not success:
            runtime.ui.error("Compare failed. Check logs in the external engine.")
            return {"status": "error"}

        report = _load_report(report_path)
        summary = report.get("summary", {})
        changed_count = (
            int(summary.get("modified", 0))
            + int(summary.get("added", 0))
            + int(summary.get("deleted", 0))
        )

        if changed_count == 0:
            runtime.ui.info("Compare completed. IDE and folder views are in sync.")
            return {"status": "success", "action": "none"}

        result = runtime.ui.show_compare_dialog(
            _object_items(report, "modified"),
            _object_items(report, "deleted"),
            _object_items(report, "added"),
            int(summary.get("unchanged", 0)),
            None,
        )
        action = (result or {}).get("action", "close")
        selected_guids = _selected_guids((result or {}).get("selected") or [], ide_runtime_common.normalize_guid)

        if action == "import":
            if not selected_guids:
                runtime.ui.warning("No objects selected for import.")
                return {"status": "success", "action": "none"}
            if ide_run_action.run_action(
                "import",
                system,
                project,
                base_dir,
                view_root=params.get("view_root"),
                layout_mode=params.get("layout"),
                selected_guids=selected_guids,
            ):
                runtime.ui.info("Selected import completed from compare UI.")
                return {"status": "success", "action": "import", "selected_guids": selected_guids}
            runtime.ui.error("Import failed from compare UI.")
            return {"status": "error", "action": "import"}

        if action == "export":
            if not selected_guids:
                runtime.ui.warning("No objects selected for export.")
                return {"status": "success", "action": "none"}
            confirm_overwrite_fn = None
            if not runtime.is_headless and hasattr(runtime.ui, "confirm_overwrite_dirty"):
                confirm_overwrite_fn = runtime.ui.confirm_overwrite_dirty
            if ide_run_action.run_action(
                "export",
                system,
                project,
                base_dir,
                view_root=params.get("view_root"),
                layout_mode=params.get("layout"),
                selected_guids=selected_guids,
                overwrite_dirty=params.get("overwrite_dirty"),
                remove_orphans=params.get("remove_orphans"),
                confirm_overwrite_fn=confirm_overwrite_fn,
            ):
                runtime.ui.info("Selected export completed from compare UI.")
                return {"status": "success", "action": "export", "selected_guids": selected_guids}
            runtime.ui.error("Export failed from compare UI.")
            return {"status": "error", "action": "export"}

        runtime.ui.info("Compare UI closed without changes.")
        return {"status": "success", "action": "close"}
    except Exception as e:
        runtime.ui.error("Error invoking compare UI: " + str(e))
        return {"status": "error", "error": str(e)}

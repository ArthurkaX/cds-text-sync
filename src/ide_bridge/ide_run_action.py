# -*- coding: utf-8 -*-
"""
ide_run_action.pyw - Common entrypoint for export, import, compare actions.
Delegates heavy lifting to the external engine.
Must be compatible with IronPython 2.7.
"""
from __future__ import print_function
import os
import sys

import ide_runtime_common
import ide_export_snapshot
import ide_apply_patch
import ide_backup

def _selected_guid_args(selected_guids):
    guids = []
    seen = {}
    for guid in selected_guids or []:
        value = ide_runtime_common.normalize_guid(guid)
        if value and value not in seen:
            seen[value] = True
            guids.append(value)
    if not guids:
        return []
    return ["--filter-guids", ",".join(guids)]


def run_action(
    action,
    system,
    project,
    project_root,
    dump_root=None,
    view_root=None,
    layout_mode=None,
    selected_guids=None,
    include_objects=False,
):
    """
    1. Dump IDE.xml
    2. Invoke Python 3 engine_cli.py
    3. If action == 'import', apply IMPORT.xml
    """
    project_layout = ide_runtime_common.layout(project_root, view_root=view_root, layout_mode=layout_mode)
    dump_root = dump_root or project_layout.dump_root
    snapshot_name = "IDE.current.xml" if action == "compare" else "IDE.xml"
    ide_xml_path = os.path.join(dump_root, snapshot_name)
    views_path = project_layout.view_root
    verbose_logging, log_path = ide_runtime_common.project_logging_config(project_root, dump_root)
    detailed_log = ide_runtime_common.make_detailed_logger(log_path)
    
    # Ensure dump dir exists
    if not os.path.exists(dump_root):
        os.makedirs(dump_root)
        
    # 1. Export Snapshot
    if not ide_export_snapshot.export_snapshot(system, project, ide_xml_path, log_fn=detailed_log):
        ide_runtime_common.log_error("Failed to export native IDE snapshot.")
        return False
    
    # 2. Invoke Engine CLI
    args = [action, "--project-root", project_root, "--snapshot", ide_xml_path, "--view-root", views_path]
    args.extend(_selected_guid_args(selected_guids))
    
    if action == "compare":
        report_path = os.path.join(dump_root, "compare_report.json")
        args.extend(["--report", report_path])
        if include_objects:
            args.append("--include-objects")
    elif action == "import":
        patch_path = os.path.join(dump_root, "IMPORT.xml")
        args.extend(["--patch", patch_path])

    if not ide_runtime_common.run_external_engine(args, project_root=project_root, dump_root=dump_root):
        ide_runtime_common.log_error("External engine action failed.")
        return False
    
    # 3. Apply Patch if needed
    if action == "import":
        if verbose_logging and detailed_log:
            detailed_log("Applying changes from " + patch_path)
        if not ide_backup.ensure_pre_import_backup(project, project_root, project_layout.backup_root, patch_path):
            ide_runtime_common.log_error("Pre-import backup failed. Import was not applied.")
            return False
        apply_result = ide_apply_patch.apply_patch(system, project, patch_path)
        if not apply_result:
            if hasattr(apply_result, "summary"):
                ide_runtime_common.log_error("Patch apply result: " + apply_result.summary())
            ide_runtime_common.log_error("Failed to apply patch to IDE.")
            return False

    ide_runtime_common.log_info("Action " + action + " completed successfully.")
    return True

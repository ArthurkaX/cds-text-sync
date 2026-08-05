# -*- coding: utf-8 -*-
"""
ide_run_action.py - Common entrypoint for export, import, compare actions.
Delegates heavy lifting to the external engine.
Must be compatible with IronPython 2.7.
"""
from __future__ import print_function
import os

import ide_runtime_common
import ide_export_snapshot
import ide_apply_patch
import ide_backup
from _project_settings import load_project_settings

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


def _show_warning(system, message):
    try:
        if system and hasattr(system, "ui") and hasattr(system.ui, "warning"):
            system.ui.warning(message)
            return
    except Exception:
        pass
    try:
        if system and hasattr(system, "ui") and hasattr(system.ui, "info"):
            system.ui.info("Warning:\n" + message)
            return
    except Exception:
        pass
    ide_runtime_common.log_error(message)


def _show_info(system, message):
    try:
        if system and hasattr(system, "ui") and hasattr(system.ui, "info"):
            system.ui.info(message)
            return
    except Exception:
        pass
    ide_runtime_common.log_info(message)


def _completion_popup_enabled(project_root):
    try:
        settings = load_project_settings(project_root)
        return bool(settings.get("show_completion_popup", True))
    except Exception:
        return True


def _completion_message(action, views_path, dump_root, ide_xml_path, patch_path=None, apply_result=None, pending_import=None, kept_orphans=None):
    if action == "export":
        message = (
            "Export completed successfully.\n\n"
            "View root:\n{0}\n\n"
            "Snapshot:\n{1}\n\n"
            "Manifest:\n{2}"
        ).format(
            views_path,
            ide_xml_path,
            os.path.join(dump_root, "manifest.json"),
        )
        if pending_import:
            message += (
                "\n\nPending import (locally modified, not overwritten):\n"
                + "\n".join(pending_import)
            )
        if kept_orphans:
            message += (
                "\n\nUnmanaged files kept (re-run and tick 'Remove' to delete):\n"
                + "\n".join(kept_orphans)
            )
        return message
    if action == "import":
        summary = apply_result.summary() if hasattr(apply_result, "summary") else "success"
        return (
            "Import completed successfully.\n\n"
            "Patch:\n{0}\n\n"
            "Result:\n{1}"
        ).format(patch_path or os.path.join(dump_root, "IMPORT.xml"), summary)
    return "Action " + action + " completed successfully."


def _read_json_file(path):
    try:
        import json
        with open(path, "r") as handle:
            return json.load(handle)
    except Exception:
        return None


def _dirty_preflight(project_root, dump_root, views_path, selected_guids, warning_fn):
    """Run the engine dirty check before an export.

    Returns the dirty report dict, or None when there is nothing to check
    (first export) or the check could not run (export then proceeds in the
    safe skip mode).
    """
    manifest_path = os.path.join(dump_root, "manifest.json")
    if not os.path.exists(manifest_path):
        return None
    report_path = os.path.join(dump_root, "dirty_report.json")
    args = [
        "check-dirty",
        "--project-root", project_root,
        "--view-root", views_path,
        "--report", report_path,
    ]
    args.extend(_selected_guid_args(selected_guids))
    if not ide_runtime_common.run_external_engine(
        args, project_root=project_root, dump_root=dump_root, warning_fn=warning_fn
    ):
        ide_runtime_common.log_error(
            "Dirty check failed; export will keep locally-modified files untouched."
        )
        return None
    return _read_json_file(report_path)


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
    overwrite_dirty=None,
    remove_orphans=None,
    confirm_overwrite_fn=None,
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

    def warning_fn(message):
        _show_warning(system, message)

    # 0. Dirty preflight for export: never silently overwrite local edits, and
    # softly propose (never force) removing unmanaged files.
    engine_overwrite_dirty = bool(overwrite_dirty)
    engine_remove_orphans = bool(remove_orphans)
    pending_import = []
    kept_orphans = []
    if action == "export":
        report = _dirty_preflight(project_root, dump_root, views_path, selected_guids, warning_fn)
        dirty_items = (report or {}).get("dirty") or []
        orphan_items = (report or {}).get("orphans") or []
        if dirty_items or orphan_items:
            if confirm_overwrite_fn is not None:
                decision = confirm_overwrite_fn(report)
                if decision is None:
                    _show_info(
                        system,
                        "Export cancelled. No files were changed.\n\n"
                        "Run Import first to bring the local edits into the IDE.",
                    )
                    ide_runtime_common.log_info(
                        "Export cancelled by user: local changes present."
                    )
                    return True
                engine_overwrite_dirty = bool(decision.get("overwrite_dirty"))
                engine_remove_orphans = bool(decision.get("remove_orphans"))
            if not engine_overwrite_dirty:
                pending_import = [
                    item.get("path") for item in dirty_items if item.get("path")
                ]
            if not engine_remove_orphans:
                kept_orphans = [
                    item.get("path") for item in orphan_items if item.get("path")
                ]

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
    elif action == "export":
        if engine_overwrite_dirty:
            args.append("--overwrite-dirty")
        if engine_remove_orphans:
            args.append("--remove-orphans")

    if not ide_runtime_common.run_external_engine(args, project_root=project_root, dump_root=dump_root, warning_fn=warning_fn):
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
    if action in ("export", "import") and _completion_popup_enabled(project_root):
        _show_info(
            system,
            _completion_message(
                action,
                views_path,
                dump_root,
                ide_xml_path,
                patch_path=os.path.join(dump_root, "IMPORT.xml") if action == "import" else None,
                apply_result=apply_result if action == "import" else None,
                pending_import=pending_import if action == "export" else None,
                kept_orphans=kept_orphans if action == "export" else None,
            ),
        )
    return True

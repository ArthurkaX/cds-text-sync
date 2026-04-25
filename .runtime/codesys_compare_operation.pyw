# -*- coding: utf-8 -*-
"""
codesys_compare_operation.py - Shared compare workflow with interactive or headless UI.
"""
from __future__ import print_function
import os
import time

from codesys_runtime import resolve_runtime, make_json_safe
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_error, log_warning,
    get_project_prop, check_version_compatibility, set_info_logging,
    finalize_sync_operation, create_safety_backup, resolve_projects
)
from codesys_managers import classify_object
from codesys_compare_engine import find_all_changes, perform_import_items, create_import_managers


def build_compare_report(base_dir, version_ok, version_msg, different, new_in_ide,
                         new_on_disk, moved, unchanged_count, elapsed):
    result = {
        "project_open": True,
        "base_dir": base_dir,
        "version_ok": bool(version_ok),
        "version_message": version_msg,
        "summary": {
            "modified": len(different),
            "new_in_ide": len(new_in_ide),
            "new_on_disk": len(new_on_disk),
            "moved": len(moved),
            "unchanged": unchanged_count
        },
        "changes": {
            "modified": different,
            "new_in_ide": new_in_ide,
            "new_on_disk": new_on_disk,
            "moved": moved
        },
        "elapsed_seconds": round(elapsed, 3)
    }
    return make_json_safe(result)


def _derive_selection_from_plan(sync_plan, selected_items):
    """Map selected compare-dialog items back to normalized sync-plan entries."""
    if not sync_plan:
        return selected_items or []

    categories = sync_plan.get("categories", {})
    selected_items = selected_items or []
    if not selected_items:
        return []

    selected_paths = set()
    for item in selected_items:
        path = item.get("path") or item.get("ide_path") or item.get("disk_path")
        if path:
            selected_paths.add(path)

    derived = []
    for category_name in ("modified", "ide_only", "disk_only", "moved"):
        for item in categories.get(category_name, []):
            item_path = item.get("path") or item.get("ide_path") or item.get("disk_path")
            if item_path in selected_paths:
                derived.append(item)
    return derived


def perform_import(runtime, primary_project, base_dir, selected, unchanged_count=0, sync_plan=None):
    if not selected and sync_plan:
        from codesys_compare_engine import plan_items_for_import
        selected = plan_items_for_import(sync_plan)
    elif selected and sync_plan:
        selected = _derive_selection_from_plan(sync_plan, selected)

    if not selected:
        runtime.ui.info("No files selected for import.")
        return {"status": "cancelled", "reason": "no_selection"}

    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    backup_filename = create_safety_backup(base_dir, projects_obj, selected)

    updated, created, failed, deleted, moved = perform_import_items(
        primary_project, base_dir, selected, globals()
    )

    message = "Import complete!\n\nUpdated: {}, Created: {}, Moved: {}, Deleted: {}, Failed: {} (Identical: {})".format(
        updated, created, moved, deleted, failed, unchanged_count)
    if backup_filename:
        message += "\n\nBackup created: .project/" + backup_filename
    runtime.ui.info(message)

    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    finalize_sync_operation(base_dir, projects_obj, is_import=True)
    return {
        "status": "success",
        "summary": {
            "updated": updated,
            "created": created,
            "moved": moved,
            "deleted": deleted,
            "failed": failed,
            "identical": unchanged_count
        },
        "backup_filename": backup_filename
    }


def perform_export(runtime, base_dir, selected, unchanged_count=0, sync_plan=None):
    if not selected and sync_plan:
        categories = sync_plan.get("categories", {})
        selected = []
        selected.extend(categories.get("modified", []))
        selected.extend(categories.get("disk_only", []))
        selected.extend(categories.get("ide_only", []))
        selected.extend(categories.get("moved", []))
    elif selected and sync_plan:
        selected = _derive_selection_from_plan(sync_plan, selected)

    if not selected:
        runtime.ui.info("No objects selected for export.")
        return {"status": "cancelled", "reason": "no_selection"}

    property_accessors = {}
    context = {
        "export_dir": base_dir,
        "exported_paths": set(),
        "property_accessors": property_accessors
    }

    managers = create_import_managers()

    count_created = 0
    count_updated = 0
    count_removed = 0
    count_failed = 0

    for item in selected:
        obj = item.get("obj")

        if not obj:
            file_path = item.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    count_removed += 1
                except Exception as error:
                    log_error("Could not remove orphaned file " + item.get("path") + ": " + safe_str(error))
                    count_failed += 1
            continue

        resolution = classify_object(obj)
        effective_type = resolution.get("manager_key") or resolution.get("semantic_kind") or resolution.get("canonical_guid")
        is_xml = bool(resolution.get("is_xml"))
        should_skip = bool(resolution.get("should_skip"))
        if should_skip:
            continue

        if resolution.get("semantic_kind") == "property":
            try:
                obj_guid = safe_str(obj.guid)
                if obj_guid not in context["property_accessors"]:
                    context["property_accessors"][obj_guid] = {"get": None, "set": None}

                for child in obj.get_children():
                    child_name = child.get_name().upper()
                    if child_name == "GET":
                        context["property_accessors"][obj_guid]["get"] = child
                    elif child_name == "SET":
                        context["property_accessors"][obj_guid]["set"] = child
            except Exception:
                pass

        if is_xml:
            manager = managers.get(effective_type, managers["native"])
        elif effective_type in managers:
            manager = managers[effective_type]
        else:
            manager = managers["default"]

        context["effective_type"] = effective_type
        try:
            result = manager.export(obj, context)
            if result == "new":
                count_created += 1
            elif result == "updated":
                count_updated += 1

            if item.get("is_moved") and item.get("file_path"):
                old_file = item["file_path"]
                if os.path.exists(old_file):
                    try:
                        os.remove(old_file)
                        log_info("Removed stale moved file: " + old_file)
                        count_removed += 1
                    except Exception as error:
                        log_warning("Could not remove old moved file: " + safe_str(error))
        except Exception as error:
            log_error("Export failed for " + item["name"] + ": " + safe_str(error))
            count_failed += 1

    summary = "Updated: {}, Created: {}, Removed: {}, Failed: {} (Identical: {})".format(
        count_updated, count_created, count_removed, count_failed, unchanged_count)

    runtime.ui.info("Export complete!\n\n" + summary)

    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    finalize_sync_operation(base_dir, projects_obj, is_import=False)
    return {
        "status": "success",
        "summary": {
            "updated": count_updated,
            "created": count_created,
            "removed": count_removed,
            "failed": count_failed,
            "identical": unchanged_count
        }
    }


def compare_project(runtime=None, params=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    quiet_compare = not bool(params.get("compare_verbose", False) or params.get("verbose", False))
    previous_info_state = True
    try:
        previous_info_state = getattr(__import__("codesys_utils"), "_logger").info_enabled
    except Exception:
        previous_info_state = True
    set_info_logging(not quiet_compare)

    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}

    try:
        version_ok, version_msg = check_version_compatibility(base_dir)
        if not version_ok and not quiet_compare:
            print("WARNING: " + safe_str(version_msg))
            print("The export was created with a different version of the sync script.")
            print("Comparison results may be unreliable.\n")

        if not quiet_compare:
            print("=== Starting Project Comparison ===")
            print("Comparing: CODESYS IDE <-> " + base_dir)

        start_time = time.time()
        export_xml = get_project_prop("cds-sync-export-xml", False)

        if not quiet_compare:
            print("Comparing IDE objects with disk...")

        results = find_all_changes(base_dir, projects_obj, export_xml=export_xml, verbose=not quiet_compare)

        different = results["different"]
        new_in_ide = results["new_in_ide"]
        new_on_disk = results["new_on_disk"]
        moved = results.get("moved", [])
        unchanged_count = results["unchanged_count"]

        elapsed = time.time() - start_time
        report = build_compare_report(
            base_dir, version_ok, version_msg, different, new_in_ide,
            new_on_disk, moved, unchanged_count, elapsed
        )
        report["sync_plan"] = results.get("sync_plan", {})

        diff_lines = []
        for item in different:
            diff_lines.append("  M  " + item["path"] + "  (" + item["type"] + ")")
        for item in new_in_ide:
            diff_lines.append("  +  " + item["path"] + "  (" + item["type"] + ")")
        for item in new_on_disk:
            diff_lines.append("  *  " + item["path"] + "  (new on disk)")
        for item in moved:
            diff_lines.append("  ~  " + item["name"] + "  (" + item["type"] + ")  IDE:" + item["ide_path"] + " -> Disk:" + item["disk_path"])

        log_info("COMPARE: M:" + str(len(different)) + " +:" + str(len(new_in_ide))
                 + " *:" + str(len(new_on_disk))
                 + " ~:" + str(len(moved))
                 + " =:" + str(unchanged_count) + " | {:.2f}s".format(elapsed))
        if diff_lines:
            log_info("DIFF:\n" + "\n".join(diff_lines))

        if quiet_compare:
            print("Summary: M:" + str(len(different)) + " +:" + str(len(new_in_ide))
                  + " *:" + str(len(new_on_disk))
                  + " ~:" + str(len(moved))
                  + " =:" + str(unchanged_count) + " | {:.2f}s".format(elapsed))
        else:
            print("")
            if diff_lines:
                print("CHANGES:")
                for line in diff_lines:
                    print(line)
            else:
                print("No differences found - IDE and disk are in sync!")

            print("")
            print("Summary: M:" + str(len(different)) + " +:" + str(len(new_in_ide))
                  + " *:" + str(len(new_on_disk))
                  + " ~:" + str(len(moved))
                  + " =:" + str(unchanged_count) + " | {:.2f}s".format(elapsed))

        if not diff_lines:
            if not quiet_compare:
                runtime.ui.info("IDE and Disk are in sync!\n\nObjects checked: " + str(unchanged_count))
            report["action"] = "sync"
            return report

        ui_result = runtime.ui.show_compare_dialog(
            different, new_in_ide, new_on_disk, unchanged_count, moved
        )
        action = ui_result.get("action", "close")
        selected = ui_result.get("selected", [])
        selected = _derive_selection_from_plan(report.get("sync_plan"), selected)

        if action == "import":
            report["action"] = "import"
            report["operation"] = perform_import(runtime, projects_obj.primary, base_dir, selected, unchanged_count, report.get("sync_plan"))
            return report

        if action == "export":
            report["action"] = "export"
            report["operation"] = perform_export(runtime, base_dir, selected, unchanged_count, report.get("sync_plan"))
            return report

        report["action"] = "report"
        return report
    finally:
        set_info_logging(previous_info_state)


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    quiet_compare = not bool(params.get("compare_verbose", False) or params.get("verbose", False))
    previous_info_state = True
    try:
        previous_info_state = getattr(__import__("codesys_utils"), "_logger").info_enabled
    except Exception:
        previous_info_state = True
    set_info_logging(not quiet_compare)

    try:
        base_dir, error = load_base_dir()
        if error:
            return {"status": "error", "error": error}

        if base_dir:
            init_logging(base_dir)

        return compare_project(runtime=runtime, params=params)
    finally:
        set_info_logging(previous_info_state)

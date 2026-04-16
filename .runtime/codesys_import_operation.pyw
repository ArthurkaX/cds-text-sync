# -*- coding: utf-8 -*-
"""
codesys_import_operation.py - Shared import workflow for disk -> CODESYS sync.
"""
from __future__ import print_function
import time

from codesys_runtime import resolve_runtime
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_warning,
    resolve_projects, get_project_prop, check_version_compatibility,
    finalize_sync_operation, create_safety_backup
)
from codesys_compare_engine import find_all_changes, perform_import_items, plan_items_for_import


def import_project(runtime=None, params=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)

    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}

    version_ok, version_msg = check_version_compatibility(base_dir)
    if not version_ok:
        message = "Version Mismatch Warning!\n\n" + version_msg + "\n\n"
        message += "The export was created with a different version of the sync script.\n"
        message += "This may cause unexpected behavior during import.\n\n"
        message += "Recommendation: Re-export the project with the current script version.\n\n"
        message += "Continue anyway?"
        if not runtime.ui.ask_yes_no("Version Mismatch Warning", message):
            print("Import cancelled due to version mismatch.")
            return {"status": "cancelled", "reason": "version_mismatch"}

    print("=== Starting Project Import ===")
    print("Importing from: " + base_dir)
    start_time = time.time()

    export_xml = get_project_prop("cds-sync-export-xml", False)

    print("Comparing IDE with disk...")
    results = find_all_changes(base_dir, projects_obj, export_xml=export_xml)

    different = results["different"]
    new_in_ide = results["new_in_ide"]
    new_on_disk = results["new_on_disk"]
    unchanged_count = results["unchanged_count"]
    sync_plan = results.get("sync_plan", {})
    plan_categories = sync_plan.get("categories", {})

    to_import = plan_items_for_import(sync_plan)
    if not to_import:
        to_import = []
        for item in different:
            to_import.append(item)
        for item in new_on_disk:
            to_import.append({
                "name": item["name"],
                "path": item["path"],
                "file_path": item["file_path"],
                "type": "new",
                "type_guid": "",
                "obj": None
            })
        for item in new_in_ide:
            to_import.append(item)

    print("")
    print("Changes found:")
    print("  Modified (IDE<>Disk): " + str(len(plan_categories.get("modified", different))))
    print("  New on disk: " + str(len(plan_categories.get("disk_only", new_on_disk))))
    print("  Missing on disk (delete): " + str(len(plan_categories.get("ide_only", new_in_ide))))
    print("  Unchanged: " + str(unchanged_count))

    if not to_import:
        elapsed = time.time() - start_time
        message = "No changes to import.\nAll " + str(unchanged_count) + " objects are in sync."
        print(message)
        runtime.ui.info(message + "\nTime: {:.2f}s".format(elapsed))
        return {
            "status": "success",
            "summary": {
                "updated": 0,
                "created": 0,
                "moved": 0,
                "deleted": 0,
                "failed": 0,
                "identical": unchanged_count,
                "elapsed_seconds": round(elapsed, 3)
            }
        }

    print("")
    print("Importing " + str(len(to_import)) + " items to IDE:")
    for item in to_import:
        action = "delete" if item.get("is_orphan") else item["type"]
        print("  <- " + item["path"] + " (" + action + ")")

    confirm_message = "Ready to import {} changes into the IDE.\n\nModified: {}\nNew on disk: {}\nDelete orphans: {}\n\nProceed?".format(
        len(to_import), len(plan_categories.get("modified", different)), len(plan_categories.get("disk_only", new_on_disk)), len(plan_categories.get("ide_only", new_in_ide))
    )
    if not runtime.ui.ask_yes_no("Confirm Import", confirm_message):
        print("Import cancelled by user.")
        return {"status": "cancelled", "reason": "user_cancelled"}

    backup_filename = create_safety_backup(base_dir, projects_obj, to_import)
    updated, created, failed, deleted, moved = perform_import_items(
        projects_obj.primary, base_dir, to_import, globals()
    )

    elapsed = time.time() - start_time
    print("")
    print("=== Import Complete ===")
    summary = "Updated: " + str(updated) + ", Created: " + str(created) + ", Moved: " + str(moved) + ", Deleted: " + str(deleted) + ", Failed: " + str(failed) + " (Identical: " + str(unchanged_count) + ")"
    print(summary)
    if backup_filename:
        print("Backup created: .project/" + backup_filename)
    print("Time elapsed: {:.2f} seconds".format(elapsed))

    log_info("Import complete! " + summary + " Time elapsed: {:.2f}s".format(elapsed))

    try:
        from codesys_utils import save_sync_metadata
        stats = {
            "updated": updated,
            "created": created,
            "moved": moved,
            "deleted": deleted,
            "failed": failed,
            "identical": unchanged_count
        }
        save_sync_metadata(base_dir, "import", stats, elapsed)
    except Exception as error:
        log_warning("Failed to update metadata: " + safe_str(error))

    message = "Import complete!\n\n" + summary + "\nTime: {:.2f}s".format(elapsed)
    if backup_filename:
        message += "\n\nBackup created: .project/" + backup_filename
    runtime.ui.info(message)

    finalize_sync_operation(base_dir, projects_obj, is_import=True)
    return {
        "status": "success",
        "summary": {
            "updated": updated,
            "created": created,
            "moved": moved,
            "deleted": deleted,
            "failed": failed,
            "identical": unchanged_count,
            "elapsed_seconds": round(elapsed, 3)
        },
        "backup_filename": backup_filename
    }


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    base_dir, error = load_base_dir()
    if base_dir:
        init_logging(base_dir)

    return import_project(runtime=runtime, params=params)

# -*- coding: utf-8 -*-
"""
codesys_export_operation.py - Shared export workflow for CODESYS -> disk sync.
"""
from __future__ import print_function
import os
import time

from codesys_runtime import resolve_runtime
from codesys_utils import (
    safe_str, load_base_dir, log_info, log_warning, log_error,
    init_logging, backup_project_binary, resolve_projects, update_application_count_flag,
    ensure_git_configs, get_project_prop, load_sync_cache, save_sync_cache,
    build_folder_hashes, normalize_path, finalize_sync_operation
)
from codesys_managers import classify_object, build_expected_path
from codesys_compare_engine import create_import_managers, resolve_manager


def save_export_metadata(export_dir, stats, elapsed_time):
    from codesys_utils import save_sync_metadata
    save_sync_metadata(export_dir, "export", stats, elapsed_time)


def _apply_nvl_path_hint(rel_path, resolution, export_dir):
    if not rel_path or not isinstance(resolution, dict):
        return rel_path, resolution

    semantic_kind = resolution.get("semantic_kind")
    if semantic_kind not in ("gvl", "nvl_sender"):
        return rel_path, resolution

    hinted_path = rel_path
    if rel_path.endswith(".gvl.xml"):
        candidate = rel_path[:-len(".gvl.xml")] + ".nvl_sender.xml"
        candidate_full = os.path.join(export_dir, candidate.replace("/", os.sep))
        if os.path.exists(candidate_full):
            hinted_path = candidate
    elif rel_path.endswith(".nvl_sender.xml"):
        hinted_path = rel_path

    if hinted_path.endswith(".nvl_sender.xml"):
        from codesys_type_system import semantic_kind_to_guid
        profile_name = resolution.get("profile_name")
        resolution = dict(resolution)
        resolution["semantic_kind"] = "nvl_sender"
        resolution["sync_profile"] = "native_xml"
        resolution["is_xml"] = True
        resolution["manager_key"] = "nvl_sender"
        resolution["canonical_guid"] = semantic_kind_to_guid("nvl_sender", profile_name) or resolution.get("canonical_guid")
        resolution["effective_type"] = resolution.get("canonical_guid") or resolution.get("effective_type")
        resolution["type_guid"] = resolution.get("effective_type")

    return hinted_path, resolution


def cleanup_orphaned_files(export_dir, current_objects, runtime):
    orphaned_items = []

    for root, dirs, files in os.walk(export_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        rel_root = os.path.relpath(root, export_dir)
        if rel_root == ".":
            rel_root = ""

        for file_name in files:
            if file_name.startswith("."):
                continue

            if not (file_name.endswith(".st") or file_name.endswith(".xml")):
                continue

            rel_path = os.path.join(rel_root, file_name).replace("\\", "/")
            if rel_path not in current_objects:
                orphaned_items.append(rel_path)

    if not orphaned_items:
        return 0

    auto_delete = get_project_prop("cds-sync-auto-delete-orphans", False)
    should_delete = bool(auto_delete)

    if not should_delete:
        message = "The following files exist in the export directory but are NOT in the CODESYS project (orphans):\n\n"
        for item in orphaned_items[:15]:
            message += "- " + item + "\n"
        if len(orphaned_items) > 15:
            message += "... and " + str(len(orphaned_items) - 15) + " more.\n"
        message += "\nWould you like to delete these orphaned files?"
        should_delete = runtime.ui.ask_yes_no("Delete Orphaned Files?", message)

    removed_count = 0
    if should_delete:
        print("Cleaning up orphaned files...")
        for rel_path in orphaned_items:
            full_path = os.path.join(export_dir, rel_path.replace("/", os.sep))
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    removed_count += 1
                    print("Deleted: " + rel_path)
            except Exception as error:
                print("Error deleting " + rel_path + ": " + safe_str(error))

        for root, dirs, files in os.walk(export_dir, topdown=False):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            rel_root = os.path.relpath(root, export_dir)
            if rel_root == "." or not rel_root:
                continue

            rel_path = rel_root.replace("\\", "/")
            folder_needed = False
            for obj_path in current_objects:
                if obj_path.startswith(rel_path + "/"):
                    folder_needed = True
                    break

            if not folder_needed and rel_path not in current_objects:
                try:
                    if not os.listdir(root):
                        os.rmdir(root)
                        print("Deleted empty folder: " + rel_path)
                except Exception:
                    pass
        return removed_count

    print("Orphaned files ignored.")
    return 0


def export_project(export_dir, runtime=None, params=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)

    if projects_obj is None or not projects_obj.primary:
        message = "Error: 'projects' object not found or no project open."
        runtime.ui.error(message)
        return {"status": "error", "error": message}

    if not os.path.exists(export_dir):
        os.makedirs(export_dir)

    ensure_git_configs(export_dir)

    print("=== Starting Project Export ===")
    update_application_count_flag()
    start_time = time.time()
    print("Export directory: " + export_dir)

    export_xml = get_project_prop("cds-sync-export-xml", False)
    backup_binary = get_project_prop("cds-sync-backup-binary", False)
    exported_paths = set()

    if backup_binary:
        print("Binary backup enabled.")
        backup_project_binary(export_dir, projects_obj)
    else:
        print("Binary backup disabled (skipping .project copy).")

    all_objects = projects_obj.primary.get_children(recursive=True)
    print("Found " + str(len(all_objects)) + " total objects")

    exported_new = 0
    exported_updated = 0
    exported_identical = 0
    exported_failed = 0
    skipped_count = 0
    property_accessors = {}

    managers = create_import_managers()
    cache_data = load_sync_cache(export_dir)
    new_cache = {}
    if cache_data and cache_data.get("objects"):
        log_info("Sync cache loaded! Enabling accelerated export (Merkle Tree skip).")

    context = {
        "export_dir": export_dir,
        "export_xml": export_xml,
        "property_accessors": property_accessors,
        "exported_paths": exported_paths,
        "cache_data": cache_data,
        "new_cache": new_cache,
        "new_types": {}
    }

    for obj in all_objects:
        try:
            obj_guid = safe_str(obj.guid)
            resolution = classify_object(obj)
            cached_type = cache_data.get("types", {}).get(obj_guid)
            if cached_type:
                effective_type = cached_type[0]
                is_xml = cached_type[1]
                rel_path = cached_type[2] if len(cached_type) > 2 else None
                should_skip = False if rel_path else True
                rel_path, resolution = _apply_nvl_path_hint(rel_path, resolution, export_dir)
            else:
                effective_type = resolution.get("manager_key") or resolution.get("semantic_kind") or resolution.get("canonical_guid")
                is_xml = bool(resolution.get("is_xml"))
                should_skip = bool(resolution.get("should_skip"))
                rel_path = build_expected_path(obj, resolution, is_xml) if not should_skip else None
                rel_path, resolution = _apply_nvl_path_hint(rel_path, resolution, export_dir)
            manager_key = resolution.get("manager_key") or resolution.get("semantic_kind") or effective_type

            context["new_types"][obj_guid] = (effective_type, is_xml, rel_path)
            norm_path = normalize_path(rel_path) if rel_path else None

            if resolution.get("semantic_kind") == "property":
                try:
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

            if cache_data and norm_path:
                try:
                    cached_obj = cache_data.get("objects", {}).get(norm_path)
                    if cached_obj:
                        new_cache[norm_path] = cached_obj
                except Exception:
                    pass

            if should_skip:
                continue

            if is_xml:
                always_exported = resolution.get("semantic_kind") in [
                    "task_config", "nvl_sender", "nvl_receiver"
                ]
                if not always_exported and not export_xml:
                    continue

            try:
                manager = resolve_manager(managers, resolution, rel_path)
            except Exception:
                if is_xml:
                    manager = managers["native"] if manager_key not in managers else managers[manager_key]
                elif manager_key in managers:
                    manager = managers[manager_key]
                else:
                    manager = managers["default"]

            context["effective_type"] = manager_key
            result = manager.export(obj, context, rel_path=rel_path)
            if result == "new":
                exported_new += 1
            elif result == "updated":
                exported_updated += 1
            elif result == "identical":
                exported_identical += 1

        except Exception as error:
            exported_failed += 1
            log_error("Error exporting " + safe_str(obj) + ": " + safe_str(error))

    removed_count = cleanup_orphaned_files(export_dir, exported_paths, runtime)
    if removed_count is None:
        return {"status": "cancelled"}

    if new_cache:
        just_hashes = {}
        for path, entry in new_cache.items():
            just_hashes[path] = entry.get("ide_hash")
        folder_hashes = build_folder_hashes(just_hashes)
        save_sync_cache(export_dir, new_cache, folder_hashes, context.get("new_types"))
        log_info("Saved updated sync cache with {} objects and {} folders.".format(
            len(new_cache), len(folder_hashes)))

    print("=== Export Complete ===")
    elapsed_time = time.time() - start_time
    print("New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical) + ", Removed: " + str(removed_count))
    print("Skipped: " + str(skipped_count) + " objects (no textual content)")
    print("Time elapsed: {:.2f} seconds".format(elapsed_time))
    print("Completed at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))

    exported_total = exported_new + exported_updated + exported_identical
    summary = "Updated: " + str(exported_updated) + ", Created: " + str(exported_new) + ", Removed: " + str(removed_count) + ", Failed: " + str(exported_failed) + " (Identical: " + str(exported_identical) + ")"
    log_info("Export complete! " + summary + " Time elapsed: {:.2f}s".format(elapsed_time))

    stats = {
        "new": exported_new,
        "updated": exported_updated,
        "identical": exported_identical,
        "removed": removed_count,
        "failed": exported_failed,
        "total": exported_total
    }
    save_export_metadata(export_dir, stats, elapsed_time)

    runtime.ui.info("Export complete!\n\n" + summary + "\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))
    finalize_sync_operation(export_dir, projects_obj, is_import=False)

    return {
        "status": "success",
        "summary": {
            "updated": exported_updated,
            "created": exported_new,
            "removed": removed_count,
            "failed": exported_failed,
            "identical": exported_identical,
            "elapsed_seconds": round(elapsed_time, 3)
        }
    }


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)

    base_dir, error = load_base_dir()
    if error:
        runtime.ui.warning(error)
        return {"status": "error", "error": error}

    init_logging(base_dir)
    return export_project(base_dir, runtime=runtime, params=params)

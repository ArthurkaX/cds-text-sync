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
    set_info_logging, set_console_silence,
    ensure_git_configs, get_project_prop, load_sync_cache, save_sync_cache,
    build_folder_hashes, normalize_path, finalize_sync_operation, get_quick_ide_hash
)
from codesys_managers import classify_object, build_expected_path
from codesys_compare_engine import create_import_managers, resolve_manager


def save_export_metadata(export_dir, stats, elapsed_time):
    from codesys_utils import save_sync_metadata
    save_sync_metadata(export_dir, "export", stats, elapsed_time)


def _ensure_cache_entry_after_export(obj, rel_path, file_path, result, is_xml, manager, context):
    """Backfill missing object cache entries after a successful export.

    Export and compare both rely on sync_cache.json. If a manager export
    succeeds but forgets to populate context['new_cache'], compare falls back
    to live IDE extraction and can produce false diffs immediately after export.
    """
    if result not in ("new", "updated", "identical"):
        return
    if not rel_path or not file_path or not os.path.exists(file_path):
        return

    new_cache = context.get("new_cache")
    if new_cache is None:
        return

    norm_path = normalize_path(rel_path)
    if norm_path in new_cache:
        return

    ide_hash = None
    try:
        if is_xml:
            if hasattr(manager, "_hash_file"):
                ide_hash = manager._hash_file(file_path)
        else:
            ide_hash = get_quick_ide_hash(obj, False)
    except Exception as e:
        log_warning("Failed to synthesize cache hash for %s (%s): %s" % (
            safe_str(obj.get_name()) if obj and hasattr(obj, "get_name") else "<unknown>",
            rel_path,
            safe_str(e)
        ))
        return

    if not ide_hash:
        log_warning("Export succeeded but cache hash is empty for %s (%s)" % (
            safe_str(obj.get_name()) if obj and hasattr(obj, "get_name") else "<unknown>",
            rel_path
        ))
        return

    try:
        stat_info = os.stat(file_path)
        new_cache[norm_path] = {
            "ide_hash": ide_hash,
            "disk_mtime": int(stat_info.st_mtime),
            "disk_size": stat_info.st_size
        }
        log_warning("Recovered missing export cache entry for %s (%s)" % (
            safe_str(obj.get_name()) if obj and hasattr(obj, "get_name") else "<unknown>",
            rel_path
        ))
    except Exception as e:
        log_warning("Failed to recover cache entry for %s (%s): %s" % (
            safe_str(obj.get_name()) if obj and hasattr(obj, "get_name") else "<unknown>",
            rel_path,
            safe_str(e)
        ))


def build_export_plan(all_objects, export_dir, cache_data=None):
    """Build a structured export plan from all IDE objects.

    Returns a dict:
        plan_items: list of export plan items, each containing:
            obj, resolution, rel_path, effective_type, is_xml,
            manager_key, should_skip
        property_accessors: collected accessor dict
        new_types: type cache dict {guid: (eff_type, is_xml, rel_path)}
    """
    property_accessors = {}
    plan_items = []
    new_types = {}

    for obj in all_objects:
        try:
            obj_guid = safe_str(obj.guid)
            resolution = classify_object(obj)
            cached_type = None
            if cache_data:
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
                rel_path = build_expected_path(obj, resolution) if not should_skip else None
                rel_path, resolution = _apply_nvl_path_hint(rel_path, resolution, export_dir)

            manager_key = resolution.get("manager_key") or resolution.get("semantic_kind") or effective_type

            new_types[obj_guid] = (effective_type, is_xml, rel_path)

            if resolution.get("semantic_kind") == "property":
                try:
                    if obj_guid not in property_accessors:
                        property_accessors[obj_guid] = {"get": None, "set": None}
                    for child in obj.get_children():
                        child_name = child.get_name().upper()
                        if child_name == "GET":
                            property_accessors[obj_guid]["get"] = child
                        elif child_name == "SET":
                            property_accessors[obj_guid]["set"] = child
                except Exception:
                    pass

            plan_items.append({
                "obj": obj,
                "resolution": resolution,
                "rel_path": rel_path,
                "effective_type": effective_type,
                "is_xml": is_xml,
                "manager_key": manager_key,
                "should_skip": should_skip,
                "norm_path": normalize_path(rel_path) if rel_path else None,
            })
        except Exception as error:
            log_error("Error classifying " + safe_str(obj) + ": " + safe_str(error))

    return {
        "plan_items": plan_items,
        "property_accessors": property_accessors,
        "new_types": new_types,
    }


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


def cleanup_orphaned_files(export_dir, current_objects, runtime, verbose=False):
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
        if verbose:
            print("Cleaning up orphaned files...")
        for rel_path in orphaned_items:
            full_path = os.path.join(export_dir, rel_path.replace("/", os.sep))
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    removed_count += 1
                    if verbose:
                        print("Deleted: " + rel_path)
            except Exception as error:
                if verbose:
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
                        if verbose:
                            print("Deleted empty folder: " + rel_path)
                except Exception:
                    pass
        return removed_count

    if verbose:
        print("Orphaned files ignored.")
    return 0


def export_project(export_dir, runtime=None, params=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    verbose = bool(params.get("export_verbose", False) or params.get("verbose", False))
    previous_info_state = True
    previous_console_silence = False
    try:
        previous_info_state = getattr(__import__("codesys_utils"), "_logger").info_enabled
        previous_console_silence = getattr(__import__("codesys_utils"), "_logger").console_silent
    except Exception:
        previous_info_state = True
        previous_console_silence = False
    set_info_logging(not verbose)
    set_console_silence(not verbose)
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)

    try:
        if projects_obj is None or not projects_obj.primary:
            message = "Error: 'projects' object not found or no project open."
            runtime.ui.error(message)
            return {"status": "error", "error": message}

        if not os.path.exists(export_dir):
            os.makedirs(export_dir)

        ensure_git_configs(export_dir)

        update_application_count_flag()
        start_time = time.time()
        if verbose:
            print("=== Starting Project Export ===")
            print("Export directory: " + export_dir)

        export_xml = get_project_prop("cds-sync-export-xml", False)
        backup_binary = get_project_prop("cds-sync-backup-binary", False)

        if backup_binary:
            if verbose:
                print("Binary backup enabled.")
            backup_project_binary(export_dir, projects_obj, verbose=verbose)
        else:
            if verbose:
                print("Binary backup disabled (skipping .project copy).")

        all_objects = projects_obj.primary.get_children(recursive=True)
        if verbose:
            print("Found " + str(len(all_objects)) + " total objects")

        managers = create_import_managers()
        cache_data = load_sync_cache(export_dir)
        new_cache = {}
        if cache_data and cache_data.get("objects"):
            log_info("Sync cache loaded! Enabling accelerated export (Merkle Tree skip).")

        plan = build_export_plan(all_objects, export_dir, cache_data=cache_data)
        plan_items = plan["plan_items"]
        property_accessors = plan["property_accessors"]
        new_types = plan["new_types"]

        exported_new = 0
        exported_updated = 0
        exported_identical = 0
        exported_failed = 0
        skipped_count = 0
        exported_paths = set()

        context = {
            "export_dir": export_dir,
            "export_xml": export_xml,
            "property_accessors": property_accessors,
            "exported_paths": exported_paths,
            "cache_data": cache_data,
            "new_cache": new_cache,
            "new_types": new_types,
        }

        for item in plan_items:
            try:
                obj = item["obj"]
                resolution = item["resolution"]
                rel_path = item["rel_path"]
                effective_type = item["effective_type"]
                is_xml = item["is_xml"]
                manager_key = item["manager_key"]
                should_skip = item["should_skip"]
                norm_path = item["norm_path"]

                if cache_data and norm_path:
                    try:
                        cached_obj = cache_data.get("objects", {}).get(norm_path)
                        if cached_obj:
                            new_cache[norm_path] = cached_obj
                    except Exception:
                        pass

                if should_skip:
                    skipped_count += 1
                    continue

                if is_xml:
                    always_exported = resolution.get("sync_profile") == "native_xml" or resolution.get("semantic_kind") in [
                        "task_config", "nvl_sender", "nvl_receiver"
                    ]
                    if not always_exported and not export_xml:
                        skipped_count += 1
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
                context["resolution"] = resolution
                result = manager.export(obj, context, rel_path=rel_path)
                _ensure_cache_entry_after_export(
                    obj, rel_path, os.path.join(export_dir, rel_path.replace("/", os.sep)),
                    result, is_xml, manager, context
                )
                if result == "new":
                    exported_new += 1
                elif result == "updated":
                    exported_updated += 1
                elif result == "identical":
                    exported_identical += 1

            except Exception as error:
                exported_failed += 1
                log_error("Error exporting " + safe_str(item.get("obj", "unknown")) + ": " + safe_str(error))

        removed_count = cleanup_orphaned_files(export_dir, exported_paths, runtime, verbose=verbose)
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

        elapsed_time = time.time() - start_time
        summary = "Updated: " + str(exported_updated) + ", Created: " + str(exported_new) + ", Removed: " + str(removed_count) + ", Failed: " + str(exported_failed) + " (Identical: " + str(exported_identical) + ")"
        dry_report = "Export complete | " + summary + " | Skipped: " + str(skipped_count) + " | Time: {:.2f}s".format(elapsed_time)
        if verbose:
            print("=== Export Complete ===")
            print("New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical) + ", Removed: " + str(removed_count))
            print("Skipped: " + str(skipped_count) + " objects (no textual content)")
            print("Time elapsed: {:.2f} seconds".format(elapsed_time))
            print("Completed at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        else:
            print(dry_report)

        exported_total = exported_new + exported_updated + exported_identical
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
        finalize_sync_operation(export_dir, projects_obj, is_import=False, verbose=verbose)

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
    finally:
        set_info_logging(previous_info_state)
        set_console_silence(previous_console_silence)


def main(params=None, runtime=None):
    params = params or {}
    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    verbose = bool(params.get("export_verbose", False) or params.get("verbose", False))
    previous_info_state = True
    previous_console_silence = False
    try:
        previous_info_state = getattr(__import__("codesys_utils"), "_logger").info_enabled
        previous_console_silence = getattr(__import__("codesys_utils"), "_logger").console_silent
    except Exception:
        previous_info_state = True
        previous_console_silence = False
    set_info_logging(not verbose)
    set_console_silence(not verbose)

    try:
        base_dir, error = load_base_dir()
        if error:
            runtime.ui.warning(error)
            return {"status": "error", "error": error}

        init_logging(base_dir)
        return export_project(base_dir, runtime=runtime, params=params)
    finally:
        set_info_logging(previous_info_state)
        set_console_silence(previous_console_silence)

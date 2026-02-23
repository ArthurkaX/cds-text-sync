# -*- coding: utf-8 -*-
"""
Project_import.py - Import disk changes into CODESYS IDE

Uses the same comparison engine as Project_compare.py, then automatically
applies all disk-side changes to IDE (equivalent to Compare -> Select All -> Import to IDE).

Also detects new files on disk (e.g. from git pull) not yet tracked in metadata.
"""
import os
import sys
import time

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

from codesys_utils import (
    safe_str, load_base_dir, load_metadata, init_logging, log_info,
    resolve_projects
)
from codesys_compare_engine import find_all_changes, perform_import_items


def import_project(projects_obj=None, silent=False):
    """
    Main import entry point.
    Compares disk with IDE and imports all differences automatically.
    Disk is the source of truth — any IDE↔Disk mismatch results in disk winning.
    """
    projects_obj = resolve_projects(projects_obj, globals())
    
    if projects_obj is None or not projects_obj.primary:
        msg = "Error: 'projects' object not found or no project open."
        if not silent:
            system.ui.error(msg)
        else:
            print(msg)
        return
    
    base_dir, error = load_base_dir()
    if error:
        if not silent:
            system.ui.warning(error)
        else:
            print(error)
        return
    
    print("=== Starting Project Import ===")
    print("Importing from: " + base_dir)
    start_time = time.time()
    
    # Load metadata from disk
    metadata = load_metadata(base_dir)
    if not metadata:
        msg = "Metadata not found! Please run Project_export.py first."
        if not silent:
            system.ui.error(msg)
        else:
            print(msg)
        return
    
    disk_objects = metadata.get("objects", {})
    print("Loaded " + str(len(disk_objects)) + " objects from metadata")
    
    # ── Phase 1: Find all changes ──
    print("Comparing IDE with disk...")
    results = find_all_changes(base_dir, projects_obj, metadata)
    
    modified = results["modified"]
    new_on_disk = results["new_on_disk"]
    unchanged_count = results["unchanged_count"]
    
    # For import, we care about ANY difference (disk or ide side) — disk wins
    # Also include new files found on disk
    to_import = []
    
    # Modified objects where disk differs from IDE
    for item in modified:
        direction = item.get("direction", "")
        if direction in ("disk", "both", "ide"):
            # All directions: disk is source of truth for import
            to_import.append(item)
    
    # New files on disk not yet in metadata
    for item in new_on_disk:
        to_import.append({
            "name": item["name"],
            "path": item["path"],
            "file_path": item["file_path"],
            "type": "new",
            "type_guid": "",
            "obj": None
        })
    
    print("")
    print("Changes found:")
    print("  Modified (IDE<>Disk): " + str(len([m for m in modified if m.get("direction") in ("disk", "both", "ide")])))
    print("  New on disk: " + str(len(new_on_disk)))
    print("  Deleted from IDE: " + str(len(results["deleted_from_ide"])))
    print("  Unchanged: " + str(unchanged_count))
    
    if not to_import:
        elapsed = time.time() - start_time
        msg = "No changes to import.\nAll " + str(unchanged_count) + " objects are in sync."
        print(msg)
        if not silent:
            system.ui.info(msg + "\nTime: {:.2f}s".format(elapsed))
        return
    
    # Show what we're about to import
    print("")
    print("Importing " + str(len(to_import)) + " items to IDE:")
    for item in to_import:
        direction = item.get("direction", "new")
        print("  <- " + item["path"] + " (" + item["type"] + ", " + direction + ")")
    
    # ── Phase 2: Import all changes ──
    updated, created, failed = perform_import_items(
        projects_obj.primary, base_dir, to_import, metadata, globals()
    )
    
    elapsed = time.time() - start_time
    
    print("")
    print("=== Import Complete ===")
    summary = "Updated: " + str(updated) + ", Created: " + str(created) + ", Failed: " + str(failed)
    print(summary)
    print("Time elapsed: {:.2f} seconds".format(elapsed))
    
    log_info("Import complete! " + summary)
    
    if not silent:
        try:
            from codesys_ui import show_toast
            show_toast("Import Complete", summary + "\nTime: {:.2f}s".format(elapsed))
        except:
            system.ui.info("Import complete!\n\n" + summary)


def main():
    base_dir, error = load_base_dir()
    
    is_silent = globals().get("SILENT", False)
    
    if base_dir:
        init_logging(base_dir)
    
    import_project(silent=is_silent)


if __name__ == "__main__":
    main()

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

import codecs
import json

from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_warning,
    resolve_projects, get_project_prop
)
from codesys_compare_engine import find_all_changes, perform_import_items


def check_version_compatibility(base_dir, silent=False):
    """Check if export was done with compatible script version"""
    from codesys_constants import SCRIPT_VERSION
    
    proj_version = get_project_prop("cds-sync-version")
    if proj_version is None:
        proj_version = "not set"
    
    metadata_path = os.path.join(base_dir, "sync_metadata.json")
    
    if proj_version != SCRIPT_VERSION:
        msg = "Version mismatch: Project (v{}) vs Current (v{})".format(proj_version, SCRIPT_VERSION)
        return False, msg
    
    if os.path.exists(metadata_path):
        try:
            with codecs.open(metadata_path, "r", "utf-8") as f:
                data = json.load(f)
            export_version = data.get("script_version")
            if export_version and export_version != SCRIPT_VERSION:
                msg = "Version mismatch: Export (v{}) vs Current (v{})".format(export_version, SCRIPT_VERSION)
                return False, msg
        except:
            pass
    
    return True, None



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
    
    # Check version compatibility
    version_ok, version_msg = check_version_compatibility(base_dir, silent)
    if not version_ok:
        if not silent:
            msg = "Version Mismatch Warning!\n\n" + version_msg + "\n\n"
            msg += "The export was created with a different version of the sync script.\n"
            msg += "This may cause unexpected behavior during import.\n\n"
            msg += "Recommendation: Re-export the project with the current script version.\n\n"
            msg += "Continue anyway?"
            
            try:
                result = system.ui.choose(msg, ("Continue", "Cancel"))
                if result[0] == 1:
                    print("Import cancelled due to version mismatch.")
                    return
            except:
                print("WARNING: " + version_msg)
                print("Proceeding with import anyway...")
        else:
            log_warning("Version mismatch: " + version_msg)
            print("WARNING: " + version_msg)
    
    print("=== Starting Project Import ===")
    print("Importing from: " + base_dir)
    start_time = time.time()
    
    export_xml = get_project_prop("cds-sync-export-xml", False)
    
    # ── Phase 1: Find all changes ──
    print("Comparing IDE with disk...")
    results = find_all_changes(base_dir, projects_obj, export_xml=export_xml)
    
    different = results["different"]
    new_in_ide = results["new_in_ide"]
    new_on_disk = results["new_on_disk"]
    unchanged_count = results["unchanged_count"]
    
    # For import, we care about ANY difference (disk or ide side) — disk wins
    # Also include new files found on disk, and DELETE orphans from IDE
    to_import = []
    
    # Modified objects: disk wins
    for item in different:
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
        
    # Orphans in IDE (missing on disk) -> delete
    for item in new_in_ide:
        to_import.append(item)
    
    print("")
    print("Changes found:")
    print("  Modified (IDE<>Disk): " + str(len(different)))
    print("  New on disk: " + str(len(new_on_disk)))
    print("  Missing on disk (delete): " + str(len(new_in_ide)))
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
        action = "delete" if item.get("is_orphan") else item["type"]
        print("  <- " + item["path"] + " (" + action + ")")
    
    # ── Phase 2: Import all changes ──
    updated, created, failed, deleted = perform_import_items(
        projects_obj.primary, base_dir, to_import, globals()
    )
    
    elapsed = time.time() - start_time
    
    print("")
    print("=== Import Complete ===")
    summary = "Updated: " + str(updated) + ", Created: " + str(created) + ", Deleted: " + str(deleted) + ", Failed: " + str(failed)
    print(summary)
    print("Time elapsed: {:.2f} seconds".format(elapsed))
    
    log_info("Import complete! " + summary)
    
    # Update metadata after successful import
    try:
        from codesys_constants import SCRIPT_VERSION
        from codesys_utils import set_project_prop
        
        metadata = {
            "script_version": SCRIPT_VERSION,
            "last_action": "import",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_sec": round(elapsed, 2),
            "statistics": {
                "updated": updated,
                "created": created,
                "deleted": deleted,
                "failed": failed
            }
        }
        
        metadata_path = os.path.join(base_dir, "sync_metadata.json")
        with codecs.open(metadata_path, "w", "utf-8") as f:
            json.dump(metadata, f, indent=2)
        log_info("Import metadata saved to sync_metadata.json (v" + SCRIPT_VERSION + ")")
        
        set_project_prop("cds-sync-version", SCRIPT_VERSION)
    except Exception as e:
        log_warning("Failed to update metadata: " + safe_str(e))
    
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

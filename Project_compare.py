# -*- coding: utf-8 -*-
"""
Project_compare.py - Compare CODESYS project with disk files

Compares .st and .xml files between the CODESYS IDE and the sync folder to identify:
- Modified objects (content hash mismatch)
- New objects in IDE (not on disk)
- Deleted objects (on disk but not in IDE)
- New files on disk (not in metadata, e.g. from git pull)

Outputs a concise git-style difference list and saves to compare.log.
"""
import os
import sys
import codecs
import time
import imp

# --- Hidden Module Loader ---
def _load_hidden_module(name):
    """Load a .pyw module from the script directory and register it in sys.modules."""
    if name not in sys.modules:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, name + ".pyw")
        if os.path.exists(path):
            sys.modules[name] = imp.load_source(name, path)

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

# Load shared core logic
_load_hidden_module("codesys_constants")
_load_hidden_module("codesys_utils")
_load_hidden_module("codesys_managers")
_load_hidden_module("codesys_ui_diff")
_load_hidden_module("codesys_ui")
_load_hidden_module("codesys_compare_engine")

import codecs
import json

from codesys_constants import TYPE_GUIDS, SCRIPT_VERSION
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_error, log_warning,
    resolve_projects, clean_filename, get_project_prop, backup_project_binary,
    check_version_compatibility, finalize_sync_operation, create_safety_backup
)
from codesys_managers import (
    FolderManager, POUManager, NativeManager, ConfigManager, PropertyManager,
    is_graphical_pou, collect_property_accessors, classify_object
)
from codesys_compare_engine import (
    find_all_changes, perform_import_items, create_import_managers, TYPE_NAMES, build_expected_path
)



def compare_project(projects_obj=None):
    """Compare CODESYS project objects with disk files"""
    
    projects_obj = resolve_projects(projects_obj, globals())
    
    if projects_obj is None or not projects_obj.primary:
        msg = "Error: 'projects' object not found or no project open."
        system.ui.error(msg)
        return
    
    base_dir, error = load_base_dir()
    if error:
        system.ui.warning(error)
        return
    
    # Check version compatibility
    version_ok, version_msg = check_version_compatibility(base_dir)
    if not version_ok:
        print("WARNING: " + version_msg)
        print("The export was created with a different version of the sync script.")
        print("Comparison results may be unreliable.\n")
    
    print("=== Starting Project Comparison ===")
    print("Comparing: CODESYS IDE <-> " + base_dir)
    start_time = time.time()
    
    export_xml = get_project_prop("cds-sync-export-xml", False)
    
    # ── Run comparison engine ──
    print("Comparing IDE objects with disk...")
    results = find_all_changes(base_dir, projects_obj, export_xml=export_xml)
    
    different = results["different"]
    new_in_ide = results["new_in_ide"]
    new_on_disk = results["new_on_disk"]
    moved = results.get("moved", [])
    unchanged_count = results["unchanged_count"]
    # ── Generate report ──
    elapsed = time.time() - start_time
    diff_lines = []
    
    if different:
        for item in different:
            line = "  M  " + item["path"] + "  (" + item["type"] + ")"
            diff_lines.append(line)
    
    if new_in_ide:
        for item in new_in_ide:
            line = "  +  " + item["path"] + "  (" + item["type"] + ")"
            diff_lines.append(line)
    
    # deleted_from_ide is now merged into new_on_disk logic
    
    if new_on_disk:
        for item in new_on_disk:
            line = "  *  " + item["path"] + "  (new on disk)"
            diff_lines.append(line)
    
    if moved:
        for item in moved:
            line = "  ~  " + item["name"] + "  (" + item["type"] + ")  IDE:" + item["ide_path"] + " -> Disk:" + item["disk_path"]
            diff_lines.append(line)
    
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
    
    log_info("COMPARE: M:" + str(len(different)) + " +:" + str(len(new_in_ide)) 
             + " *:" + str(len(new_on_disk))
             + " ~:" + str(len(moved))
             + " =:" + str(unchanged_count) + " | {:.2f}s".format(elapsed))
    if diff_lines:
        log_info("DIFF:\n" + "\n".join(diff_lines))
    
    # ── Show UI ──
    if not diff_lines:
        system.ui.info("IDE and Disk are in sync!\n\nObjects checked: " + str(unchanged_count))
    else:
        from codesys_ui import show_compare_dialog
        action, selected = show_compare_dialog(
            different, new_in_ide, new_on_disk, unchanged_count, moved
        )
        
        if action == "import":
            perform_import(projects_obj.primary, base_dir, selected, unchanged_count)
        elif action == "export":
            perform_export(base_dir, selected, unchanged_count)


def perform_import(primary_project, base_dir, selected, unchanged_count=0):
    """Import selected items via the shared engine."""
    if not selected:
        system.ui.info("No files selected for import.")
        return
    
    # Create timestamped safety backup if enabled
    projects_obj = resolve_projects(None, globals())
    backup_filename = create_safety_backup(base_dir, projects_obj, selected)
    
    updated, created, failed, deleted, moved = perform_import_items(
        primary_project, base_dir, selected, globals()
    )
    
    message = "Import complete!\n\nUpdated: {}, Created: {}, Moved: {}, Deleted: {}, Failed: {} (Identical: {})".format(
        updated, created, moved, deleted, failed, unchanged_count)
    if backup_filename:
        message += "\n\nBackup created: .project/" + backup_filename
    system.ui.info(message)

    # Handle final save and backup
    projects_obj = resolve_projects(None, globals())
    finalize_sync_operation(base_dir, projects_obj, is_import=True)


def perform_export(base_dir, selected, unchanged_count=0):
    """Trigger export for IDE-side changes"""
    if not selected:
        system.ui.info("No objects selected for export.")
        return
        
    # Property accessors collected dynamically during export loop
    property_accessors = {}
    
    context = {
        'export_dir': base_dir,
        'exported_paths': set(),
        'property_accessors': property_accessors
    }
    
    managers = create_import_managers()
    
    count_created = 0
    count_updated = 0
    count_removed = 0
    count_failed = 0
    
    for item in selected:
        obj = item.get("obj")
        
        # Scenario 1: Object missing in IDE (from 'new_on_disk' list) -> DELETION from disk
        if not obj:
            file_path = item.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    count_removed += 1
                except Exception as e:
                    log_error("Could not remove orphaned file " + item.get("path") + ": " + safe_str(e))
                    count_failed += 1
            continue
        
        # Scenario 2: Object exists in IDE -> EXPORT to disk
        from codesys_managers import classify_object
        effective_type, is_xml, should_skip = classify_object(obj)
        if should_skip: continue

        # --- PROPERTY ACCESSOR COLLECTION ---
        if effective_type == TYPE_GUIDS["property"]:
            try:
                obj_guid = safe_str(obj.guid)
                if obj_guid not in context['property_accessors']:
                    context['property_accessors'][obj_guid] = {'get': None, 'set': None}
                
                for child in obj.get_children():
                    child_name = child.get_name().upper()
                    if child_name == "GET":
                        context['property_accessors'][obj_guid]['get'] = child
                    elif child_name == "SET":
                        context['property_accessors'][obj_guid]['set'] = child
            except:
                pass

        if is_xml:
            mgr = managers.get(effective_type, managers["native"])
        elif effective_type in managers:
            mgr = managers[effective_type]
        else:
            mgr = managers["default"]

        context['effective_type'] = effective_type
        try:
            res = mgr.export(obj, context)
            if res == "new":
                count_created += 1
            elif res == "updated":
                count_updated += 1
            
            # Moved file: clean up the old file at the stale disk location
            if item.get("is_moved") and item.get("file_path"):
                old_file = item["file_path"]
                if os.path.exists(old_file):
                    try:
                        os.remove(old_file)
                        log_info("Removed stale moved file: " + old_file)
                        count_removed += 1
                    except Exception as e2:
                        log_warning("Could not remove old moved file: " + safe_str(e2))
        except Exception as e:
            log_error("Export failed for " + item["name"] + ": " + safe_str(e))
            count_failed += 1
    
    summary = "Updated: {}, Created: {}, Removed: {}, Failed: {} (Identical: {})".format(
        count_updated, count_created, count_removed, count_failed, unchanged_count)
        
    system.ui.info("Export complete!\n\n" + summary)

    # Handle final save and backup
    projects_obj = resolve_projects(None, globals())
    finalize_sync_operation(base_dir, projects_obj, is_import=False)


def main():
    base_dir, error = load_base_dir()
    
    log_file_obj = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    if base_dir:
        init_logging(base_dir)
        
        try:
            log_path = os.path.join(base_dir, "compare.log")
            log_file_obj = codecs.open(log_path, "w", "utf-8")
            
            class Tee(object):
                def __init__(self, terminal, file_obj):
                    self.terminal = terminal
                    self.file_obj = file_obj
                def write(self, message):
                    self.terminal.write(message)
                    try:
                        self.file_obj.write(message)
                    except:
                        pass
                def flush(self):
                    self.terminal.flush()
                    try:
                        self.file_obj.flush()
                    except:
                        pass
            
            sys.stdout = Tee(original_stdout, log_file_obj)
            sys.stderr = Tee(original_stderr, log_file_obj)
        except Exception as e:
            pass

    try:
        compare_project()
    finally:
        if log_file_obj:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_file_obj.close()


if __name__ == "__main__":
    main()

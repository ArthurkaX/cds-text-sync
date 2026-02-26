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

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

from codesys_constants import TYPE_GUIDS
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_error,
    resolve_projects, clean_filename, get_project_prop
)
from codesys_managers import (
    FolderManager, POUManager, NativeManager, ConfigManager, PropertyManager,
    is_graphical_pou, collect_property_accessors, classify_object
)
from codesys_compare_engine import (
    find_all_changes, perform_import_items, TYPE_NAMES, build_expected_path
)


def compare_project(projects_obj=None, silent=False):
    """Compare CODESYS project objects with disk files"""
    
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
          + " =:" + str(unchanged_count) + " | {:.2f}s".format(elapsed))
    
    log_info("COMPARE: M:" + str(len(different)) + " +:" + str(len(new_in_ide)) 
             + " *:" + str(len(new_on_disk))
             + " =:" + str(unchanged_count))
    if diff_lines:
        log_info("DIFF:\n" + "\n".join(diff_lines))
    
    # ── Show UI ──
    if not silent:
        if not diff_lines:
            system.ui.info("IDE and Disk are in sync!\n\nObjects checked: " + str(unchanged_count))
        else:
            from codesys_ui import show_compare_dialog
            action, selected = show_compare_dialog(
                different, new_in_ide, new_on_disk, unchanged_count
            )
            
            if action == "import":
                perform_import(projects_obj.primary, base_dir, selected)
            elif action == "export":
                perform_export(base_dir, selected)


def perform_import(primary_project, base_dir, selected):
    """Import selected items via the shared engine."""
    if not selected:
        system.ui.info("No files selected for import.")
        return
    
    updated, created, failed, deleted = perform_import_items(
        primary_project, base_dir, selected, globals()
    )
    
    system.ui.info("Import complete!\n\nUpdated: {}\nCreated: {}\nDeleted: {}\nFailed: {}".format(
        updated, created, deleted, failed))


def perform_export(base_dir, selected):
    """Trigger export for IDE-side changes"""
    if not selected:
        system.ui.info("No objects selected for export.")
        return
        
    # Collect all property accessors from current project
    projects_obj = resolve_projects(None, globals())
    if projects_obj and projects_obj.primary:
        all_objects = projects_obj.primary.get_children(recursive=True)
        property_accessors = collect_property_accessors(all_objects)
    else:
        property_accessors = {}
    
    context = {
        'export_dir': base_dir,
        'exported_paths': set(),
        'property_accessors': property_accessors
    }
    
    managers = {
        TYPE_GUIDS["folder"]: FolderManager(),
        TYPE_GUIDS["property"]: PropertyManager(),
        TYPE_GUIDS["task_config"]: ConfigManager(),
        TYPE_GUIDS["alarm_config"]: ConfigManager(),
        "default": POUManager(),
        "native": NativeManager()
    }
    native_mgr = NativeManager()
    
    count = 0
    for item in selected:
        obj = item.get("obj")
        if not obj: continue
        
        # Determine manager
        from codesys_managers import classify_object
        effective_type, is_xml, should_skip = classify_object(obj)
        if should_skip: continue

        if is_xml:
            mgr = managers.get(effective_type, native_mgr)
        elif effective_type in managers:
            mgr = managers[effective_type]
        else:
            mgr = managers[TYPE_GUIDS["pou"]] # Default

        context['effective_type'] = effective_type
        try:
            res = mgr.export(obj, context)
            if res: count += 1
        except Exception as e:
            log_error("Export failed for " + item["name"] + ": " + safe_str(e))
    
    system.ui.info("Exported " + str(count) + " objects.")


def main():
    base_dir, error = load_base_dir()
    
    is_silent = globals().get("SILENT", False)
    
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
        compare_project(silent=is_silent)
    finally:
        if log_file_obj:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_file_obj.close()


if __name__ == "__main__":
    main()

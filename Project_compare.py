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
    safe_str, load_base_dir, load_metadata, init_logging, log_info, log_error,
    resolve_projects, save_metadata, clean_filename
)
from codesys_managers import (
    POUManager, NativeManager, ConfigManager, PropertyManager, is_graphical_pou
)
from codesys_compare_engine import (
    find_all_changes, perform_import_items, TYPE_NAMES
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
    print("Loaded " + str(len(disk_objects)) + " objects from disk metadata")
    
    # ── Run comparison engine ──
    print("Building IDE object cache...")
    results = find_all_changes(base_dir, projects_obj, metadata)
    
    modified = results["modified"]
    new_in_ide = results["new_in_ide"]
    deleted_from_ide = results["deleted_from_ide"]
    new_on_disk = results["new_on_disk"]
    unchanged_count = results["unchanged_count"]
    
    # ── Generate report ──
    elapsed = time.time() - start_time
    diff_lines = []
    
    if modified:
        for item in modified:
            direction = item.get("direction", "")
            if direction == "ide":
                tag = "M IDE> "
            elif direction == "disk":
                tag = "M DISK>"
            elif direction == "both":
                tag = "M BOTH>"
            else:
                tag = "M      "
            line = "  " + tag + " " + item["path"] + "  (" + item["type"] + ")"
            diff_lines.append(line)
    
    if new_in_ide:
        for item in new_in_ide:
            line = "  +  " + item["path"] + "  (" + item["type"] + ")"
            diff_lines.append(line)
    
    if deleted_from_ide:
        for item in deleted_from_ide:
            line = "  -  " + item["path"] + "  (" + item["type"] + ")"
            diff_lines.append(line)
    
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
    print("Summary: M:" + str(len(modified)) + " +:" + str(len(new_in_ide)) 
          + " -:" + str(len(deleted_from_ide)) + " *:" + str(len(new_on_disk))
          + " =:" + str(unchanged_count) + " | {:.2f}s".format(elapsed))
    
    log_info("COMPARE: M:" + str(len(modified)) + " +:" + str(len(new_in_ide)) 
             + " -:" + str(len(deleted_from_ide)) + " *:" + str(len(new_on_disk))
             + " =:" + str(unchanged_count))
    if diff_lines:
        log_info("DIFF:\n" + "\n".join(diff_lines))
    
    # ── Show UI ──
    if not silent:
        if not diff_lines:
            system.ui.info("IDE and Disk are in sync!\n\nObjects checked: " + str(unchanged_count))
        else:
            # Group modified by direction
            ide_changes = [m for m in modified if m.get("direction") == "ide"]
            disk_changes = [m for m in modified if m.get("direction") == "disk"]
            both_changes = [m for m in modified if m.get("direction") == "both"]
            other_changes = [m for m in modified if m.get("direction") not in ("ide", "disk", "both")]
            all_disk = disk_changes + other_changes
            
            from codesys_ui import show_compare_dialog
            action, selected = show_compare_dialog(
                ide_changes, all_disk, both_changes,
                new_in_ide, deleted_from_ide, unchanged_count,
                new_on_disk
            )
            
            if action == "import":
                # Merge new_on_disk items into selected for import
                perform_import(projects_obj.primary, base_dir, selected, deleted_from_ide, metadata)
            elif action == "export":
                perform_export(base_dir, selected, new_in_ide, metadata)


def perform_import(primary_project, base_dir, selected, deleted_from_ide, metadata):
    """Import selected items via the shared engine."""
    if not selected:
        system.ui.info("No files selected for import.")
        return
    
    updated, created, failed = perform_import_items(
        primary_project, base_dir, selected, metadata, globals()
    )
    
    system.ui.info("Import complete!\n\nUpdated: {}\nCreated: {}\nFailed: {}".format(
        updated, created, failed))


def perform_export(base_dir, modified, new_in_ide, metadata):
    """Trigger export for IDE-side changes"""
    
    to_export = [m for m in modified if m.get("direction") in ("ide", "both")]
    to_export += new_in_ide
    
    if not to_export:
        system.ui.info("No objects selected for export.")
        return
        
    context = {
        'export_dir': base_dir,
        'metadata': metadata
    }
    
    managers = {
        TYPE_GUIDS["pou"]: POUManager(),
        TYPE_GUIDS["gvl"]: POUManager(),
        TYPE_GUIDS["dut"]: POUManager(),
        TYPE_GUIDS["itf"]: POUManager(),
        TYPE_GUIDS["property"]: PropertyManager(),
        TYPE_GUIDS["task_config"]: ConfigManager(),
    }
    native_mgr = NativeManager()
    
    count = 0
    for item in to_export:
        obj = item.get("obj")
        if not obj: continue
        
        obj_type = safe_str(obj.type)
        
        # Detect graphical POUs (LD/CFC/FBD) - route to native XML export
        use_native = False
        if obj_type in [TYPE_GUIDS["pou"], TYPE_GUIDS["action"], TYPE_GUIDS["method"]]:
            try:
                if is_graphical_pou(obj):
                    use_native = True
            except:
                pass
        
        mgr = native_mgr if use_native else managers.get(obj_type, native_mgr)
        
        try:
            res = mgr.export(obj, context)
            if res: count += 1
        except Exception as e:
            log_error("Export failed for " + item["name"] + ": " + safe_str(e))
            
    save_metadata(base_dir, metadata)
    
    system.ui.info("Exported " + str(count) + " objects.\nMetadata updated.")


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

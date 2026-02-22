# -*- coding: utf-8 -*-
"""
Project_compare.py - Compare CODESYS project with disk files

Compares .st files between the CODESYS IDE and the sync folder to identify:
- Modified objects (content hash mismatch)
- New objects in IDE (not on disk)
- Deleted objects (on disk but not in IDE)

Provides feedback through CODESYS script messages.
"""
import os
import sys
import codecs
import time
from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES
from codesys_utils import (
    safe_str, load_base_dir, load_metadata, build_object_cache,
    calculate_hash, format_st_content, init_logging, log_info,
    get_project_prop, format_property_content, resolve_projects
)
from codesys_managers import (
    get_object_path, get_parent_pou_name, export_object_content,
    collect_property_accessors
)

def compare_project(projects_obj=None, silent=False):
    """Compare CODESYS project objects with disk files"""
    
    # Resolve projects object
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
    
    # Build cache of IDE objects
    print("Building IDE object cache...")
    guid_map, name_map = build_object_cache(projects_obj.primary)
    print("Found " + str(len(guid_map)) + " objects in IDE")
    
    # Get all IDE objects
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    
    # Track comparison results
    modified = []
    new_in_ide = []
    deleted_from_ide = []
    unchanged = []
    
    # First pass: collect property accessors
    property_accessors = collect_property_accessors(all_ide_objects)
    
    # Second pass: Compare IDE objects with disk
    for obj in all_ide_objects:
        try:
            if not hasattr(obj, 'type') or not hasattr(obj, 'get_name') or not hasattr(obj, 'guid'):
                continue
            
            obj_type = safe_str(obj.type)
            obj_name = obj.get_name()
            obj_guid = safe_str(obj.guid)
            
            # Skip property accessors - handled with parent property
            if obj_type == TYPE_GUIDS["property_accessor"]:
                continue
            
            # Skip folders
            if obj_type == TYPE_GUIDS["folder"]:
                continue
            
            # Only process exportable types with ST content
            if obj_type not in EXPORTABLE_TYPES:
                continue
            
            # Check if object has textual content
            has_content = False
            try:
                if hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
                    has_content = True
                if hasattr(obj, "has_textual_implementation") and obj.has_textual_implementation:
                    has_content = True
            except:
                pass
            
            # Special handling for properties with accessors
            is_property = obj_type == TYPE_GUIDS["property"]
            if is_property and obj_guid in property_accessors:
                has_content = True
            
            if not has_content:
                continue
            
            # Build expected file path
            from codesys_utils import clean_filename
            path_parts = get_object_path(obj)
            clean_name = clean_filename(obj_name)
            
            # Handle nested objects (actions, methods, properties)
            parent_pou = get_parent_pou_name(obj)
            if parent_pou and obj_type in [TYPE_GUIDS["action"], TYPE_GUIDS["method"], TYPE_GUIDS["property"]]:
                file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
                clean_parent_pou = clean_filename(parent_pou)
                if path_parts and path_parts[-1] == clean_parent_pou:
                    path_parts = path_parts[:-1]
            else:
                file_name = clean_name + ".st"
            
            # Build relative path (always in src/)
            if path_parts:
                rel_path = "src/" + "/".join(path_parts) + "/" + file_name
            else:
                rel_path = "src/" + file_name
            
            # Get IDE content
            ide_content = None
            if is_property and obj_guid in property_accessors:
                # Property with accessors
                prop_data = property_accessors[obj_guid]
                declaration, _ = export_object_content(obj)
                
                # Get GET accessor
                get_impl = None
                if prop_data['get']:
                    get_decl, get_impl_raw = export_object_content(prop_data['get'])
                    get_impl = format_st_content(get_decl, get_impl_raw)
                
                # Get SET accessor
                set_impl = None
                if prop_data['set']:
                    set_decl, set_impl_raw = export_object_content(prop_data['set'])
                    set_impl = format_st_content(set_decl, set_impl_raw)
                
                ide_content = format_property_content(declaration, get_impl, set_impl)
            else:
                # Normal object
                declaration, implementation = export_object_content(obj)
                ide_content = format_st_content(declaration, implementation)
            
            if not ide_content or not ide_content.strip():
                continue
            
            ide_hash = calculate_hash(ide_content)
            
            # Check if file exists on disk
            if rel_path in disk_objects:
                disk_info = disk_objects[rel_path]
                disk_hash = disk_info.get("content_hash", "")
                
                if ide_hash != disk_hash:
                    modified.append({
                        "name": obj_name,
                        "path": rel_path,
                        "type": obj_type
                    })
                else:
                    unchanged.append(rel_path)
            else:
                # Object exists in IDE but not on disk
                new_in_ide.append({
                    "name": obj_name,
                    "path": rel_path,
                    "type": obj_type
                })
        
        except Exception as e:
            print("Error processing object: " + safe_str(e))
            continue
    
    # Third pass: Find objects on disk that don't exist in IDE
    for rel_path, disk_info in disk_objects.items():
        # Skip folders and non-.st files
        if disk_info.get("type") == TYPE_GUIDS["folder"]:
            continue
        if not rel_path.endswith(".st"):
            continue
        
        # Check if this object exists in IDE
        obj_guid = disk_info.get("guid")
        obj_name = disk_info.get("name")
        
        found = False
        if obj_guid and obj_guid != "N/A":
            if obj_guid in guid_map:
                found = True
        
        if not found and obj_name:
            if obj_name in name_map:
                found = True
        
        if not found and rel_path not in unchanged:
            # Check if we already counted it as modified or new
            already_counted = False
            for item in modified + new_in_ide:
                if item["path"] == rel_path:
                    already_counted = True
                    break
            
            if not already_counted:
                deleted_from_ide.append({
                    "name": obj_name,
                    "path": rel_path,
                    "type": disk_info.get("type", "unknown")
                })
    
    # Generate report
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)
    
    if modified:
        print("\nMODIFIED (" + str(len(modified)) + " objects):")
        print("-" * 80)
        for item in modified:
            print("  " + item["name"] + " (" + item["path"] + ")")
    
    if new_in_ide:
        print("\nNEW IN IDE (" + str(len(new_in_ide)) + " objects - not exported yet):")
        print("-" * 80)
        for item in new_in_ide:
            print("  " + item["name"] + " (" + item["path"] + ")")
    
    if deleted_from_ide:
        print("\nDELETED FROM IDE (" + str(len(deleted_from_ide)) + " objects - still on disk):")
        print("-" * 80)
        for item in deleted_from_ide:
            print("  " + item["name"] + " (" + item["path"] + ")")
    
    if not modified and not new_in_ide and not deleted_from_ide:
        print("\nNo differences found - IDE and disk are in sync!")
    
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("  Modified:        " + str(len(modified)))
    print("  New in IDE:      " + str(len(new_in_ide)))
    print("  Deleted from IDE: " + str(len(deleted_from_ide)))
    print("  Unchanged:       " + str(len(unchanged)))
    print("  Time elapsed:    {:.2f}s".format(elapsed))
    print("=" * 80)
    
    # Show summary dialog
    if not silent:
        summary = "Comparison Complete!\n\n"
        summary += "Modified:        " + str(len(modified)) + "\n"
        summary += "New in IDE:      " + str(len(new_in_ide)) + "\n"
        summary += "Deleted from IDE: " + str(len(deleted_from_ide)) + "\n"
        summary += "Unchanged:       " + str(len(unchanged)) + "\n\n"
        
        if modified or new_in_ide or deleted_from_ide:
            summary += "See Script Output window for details."
        else:
            summary += "IDE and disk are in sync!"
        
        system.ui.info(summary)


def main():
    base_dir, error = load_base_dir()
    
    # Check if we are being run in silent mode (e.g. from Daemon)
    is_silent = globals().get("SILENT", False)
    
    log_file_obj = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    if base_dir:
        init_logging(base_dir)
        
        # Setup redirection to compare.log
        try:
            log_path = os.path.join(base_dir, "compare.log")
            # Open with 'w' to recreate each run (truncate)
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
            # Fallback if log file cannot be opened
            pass

    try:
        compare_project(silent=is_silent)
    finally:
        # Restore and close
        if log_file_obj:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_file_obj.close()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Project_import.py - Import disk changes into CODESYS IDE

Uses the same comparison engine as Project_compare.py, then automatically
applies all disk-side changes to IDE (equivalent to Compare -> Select All -> Import to IDE).
"""
import os
import sys
import codecs
import time
import tempfile

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES
from codesys_utils import (
    safe_str, load_base_dir, load_metadata, build_object_cache,
    calculate_hash, format_st_content, init_logging, log_info, log_error,
    get_project_prop, format_property_content, resolve_projects,
    clean_filename, find_object_by_path, save_metadata, MetadataLock
)
from codesys_managers import (
    get_object_path, get_container_prefix, get_parent_pou_name,
    export_object_content, collect_property_accessors, is_nvl, is_graphical_pou,
    NativeManager
)
from codesys_import_engine import (
    create_import_managers, update_existing_object, create_new_object,
    batch_import_native_xmls, update_object_metadata, finalize_import
)


# Reverse mapping for friendly type names
TYPE_NAMES = {v: k for k, v in TYPE_GUIDS.items()}


def find_disk_changes(base_dir, projects_obj, metadata):
    """
    Compare IDE objects with disk files and return lists of changes.
    This is the same logic as Project_compare.compare_project but returns
    raw data instead of showing a UI.
    
    Returns:
        (disk_modified, deleted_from_ide, unchanged_count)
        
        disk_modified: list of dicts with keys: name, path, type, type_guid, direction, obj
        deleted_from_ide: list of dicts with keys: name, path, type, type_guid
    """
    disk_objects = metadata.get("objects", {})
    
    # Build cache of IDE objects
    guid_map, name_map = build_object_cache(projects_obj.primary)
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    
    # Track comparison results
    disk_modified = []    # Files changed on disk -> need import to IDE
    deleted_from_ide = [] # On disk but not in IDE
    unchanged_count = 0
    matched_disk_paths = set()
    
    # Collect property accessors
    property_accessors = collect_property_accessors(all_ide_objects)
    native_mgr = NativeManager()
    
    # Pass 1: Compare IDE objects with disk
    for obj in all_ide_objects:
        try:
            if not hasattr(obj, 'type') or not hasattr(obj, 'get_name') or not hasattr(obj, 'guid'):
                continue
            
            obj_type = safe_str(obj.type)
            obj_name = obj.get_name()
            obj_guid = safe_str(obj.guid)
            
            # Skip property accessors, folders, tasks
            if obj_type == TYPE_GUIDS["property_accessor"]:
                continue
            if obj_type == TYPE_GUIDS["folder"]:
                continue
            if obj_type == TYPE_GUIDS["task"]:
                continue
            
            # Determine effective type
            effective_type = obj_type
            is_xml_object = False
            
            if obj_type == TYPE_GUIDS["gvl"]:
                try:
                    if is_nvl(obj):
                        effective_type = TYPE_GUIDS["nvl_sender"]
                        is_xml_object = True
                except:
                    pass

            if not is_xml_object and effective_type in [TYPE_GUIDS["pou"], TYPE_GUIDS["action"], TYPE_GUIDS["method"]]:
                try:
                    if is_graphical_pou(obj):
                        is_xml_object = True
                except:
                    pass
            
            if effective_type in XML_TYPES:
                is_xml_object = True
            
            if effective_type not in EXPORTABLE_TYPES and effective_type not in XML_TYPES:
                continue
            
            # Build expected file path
            container = get_container_prefix(obj)
            path_parts = get_object_path(obj)
            clean_name = clean_filename(obj_name)
            
            if is_xml_object:
                file_name = clean_name + ".xml"
            else:
                parent_pou = get_parent_pou_name(obj)
                if parent_pou and obj_type in [TYPE_GUIDS["action"], TYPE_GUIDS["method"], TYPE_GUIDS["property"]]:
                    file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
                    clean_parent_pou = clean_filename(parent_pou)
                    if path_parts and path_parts[-1] == clean_parent_pou:
                        path_parts = path_parts[:-1]
                else:
                    file_name = clean_name + ".st"
            
            full_path_parts = container + path_parts
            if full_path_parts:
                rel_path = "/".join(full_path_parts) + "/" + file_name
            else:
                rel_path = file_name
            
            # Skip AlarmGroup objects
            if is_xml_object and (obj_name == "AlarmGroup" or "AlarmGroup" in rel_path):
                unchanged_count += 1
                continue
            
            # Gate XML types
            if is_xml_object and effective_type in XML_TYPES:
                always_exported = effective_type in [
                    TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]
                ]
                if not always_exported and not metadata.get("export_xml", False) \
                   and rel_path not in disk_objects:
                    continue
            
            type_name = TYPE_NAMES.get(effective_type, effective_type[:8])
            
            # Compare content
            if rel_path in disk_objects:
                matched_disk_paths.add(rel_path)
                disk_info = disk_objects[rel_path]
                meta_hash = disk_info.get("content_hash", "")
                
                if is_xml_object:
                    file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                    
                    # Get Disk Hash
                    disk_file_hash = ""
                    if os.path.exists(file_path):
                        disk_file_hash = native_mgr._hash_file(file_path)
                    
                    # Get IDE Hash
                    ide_hash = ""
                    try:
                        tmp_path = os.path.join(tempfile.gettempdir(), "cds_imp_" + clean_name + ".xml")
                        projects_obj.primary.export_native([obj], tmp_path, recursive=True)
                        if os.path.exists(tmp_path):
                            ide_hash = native_mgr._hash_file(tmp_path)
                            os.remove(tmp_path)
                    except:
                        pass
                    
                    # Detect ANY difference between IDE and disk
                    # This catches both disk-side and IDE-side changes
                    has_diff = (ide_hash != "" and disk_file_hash != "" and ide_hash != disk_file_hash)
                    
                    if has_diff:
                        disk_modified.append({
                            "name": obj_name, "path": rel_path, "type": type_name,
                            "type_guid": effective_type, "direction": "disk", "obj": obj
                        })
                    else:
                        unchanged_count += 1
                else:
                    # ST content comparison
                    ide_content = None
                    is_property = obj_type == TYPE_GUIDS["property"]
                    
                    if is_property and obj_guid in property_accessors:
                        prop_data = property_accessors[obj_guid]
                        declaration, _ = export_object_content(obj)
                        
                        get_impl = None
                        if prop_data['get']:
                            get_decl, get_impl_raw = export_object_content(prop_data['get'])
                            get_impl = format_st_content(get_decl, get_impl_raw)
                        
                        set_impl = None
                        if prop_data['set']:
                            set_decl, set_impl_raw = export_object_content(prop_data['set'])
                            set_impl = format_st_content(set_decl, set_impl_raw)
                        
                        ide_content = format_property_content(declaration, get_impl, set_impl)
                    else:
                        has_content = False
                        try:
                            if hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
                                has_content = True
                            if hasattr(obj, "has_textual_implementation") and obj.has_textual_implementation:
                                has_content = True
                        except:
                            pass
                        
                        if is_property and obj_guid in property_accessors:
                            has_content = True
                        
                        if not has_content:
                            unchanged_count += 1
                            continue
                        
                        declaration, implementation = export_object_content(obj)
                        ide_content = format_st_content(declaration, implementation)
                    
                    if not ide_content or not ide_content.strip():
                        unchanged_count += 1
                        continue
                    
                    ide_hash = calculate_hash(ide_content)
                    
                    # Read disk file content and hash
                    disk_file_hash = ""
                    file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                    if os.path.exists(file_path):
                        try:
                            with codecs.open(file_path, "r", "utf-8") as df:
                                disk_content = df.read()
                            disk_file_hash = calculate_hash(disk_content)
                        except:
                            pass
                    
                    # Detect ANY difference between IDE and disk
                    has_diff = (ide_hash != disk_file_hash)
                    
                    if has_diff:
                        disk_modified.append({
                            "name": obj_name, "path": rel_path, "type": type_name,
                            "type_guid": effective_type, "direction": "disk", "obj": obj
                        })
                    else:
                        unchanged_count += 1
            # else: object in IDE but not on disk — not relevant for import
        
        except Exception as e:
            print("Error comparing object: " + safe_str(e))
            continue
    
    # Pass 2: Find objects on disk but not in IDE (deleted from IDE)
    for rel_path, disk_info in disk_objects.items():
        if disk_info.get("type") == TYPE_GUIDS["folder"]:
            continue
        if not rel_path.endswith(".st") and not rel_path.endswith(".xml"):
            continue
        if rel_path in matched_disk_paths:
            continue
        
        obj_name = disk_info.get("name", os.path.basename(rel_path))
        obj_type_guid = disk_info.get("type", "unknown")
        type_name = TYPE_NAMES.get(obj_type_guid, obj_type_guid[:8] if len(obj_type_guid) > 8 else obj_type_guid)
        
        deleted_from_ide.append({
            "name": obj_name, "path": rel_path, "type": type_name,
            "type_guid": obj_type_guid
        })
    
    return disk_modified, deleted_from_ide, unchanged_count


def perform_import(primary_project, base_dir, to_sync, metadata):
    """
    Import disk-modified items to IDE.
    This is the same logic as Project_compare.perform_import.
    """
    if not to_sync:
        print("No files to import.")
        return 0, 0, 0
    
    import_managers = create_import_managers()
    guid_map, name_map = build_object_cache(primary_project)
    objects_meta = metadata.get("objects", {})
    folder_cache = {}
    
    updated_count = 0
    created_count = 0
    failed_count = 0
    native_batches = {}
    
    with MetadataLock(base_dir, timeout=60):
        for item in to_sync:
            try:
                rel_path = item["path"]
                abs_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                
                if not os.path.exists(abs_path):
                    continue
                
                # XML files are batched for import
                if rel_path.endswith(".xml"):
                    obj = item.get("obj")
                    if not obj:
                        obj = find_object_by_path(rel_path, primary_project)
                    
                    container = primary_project
                    is_new = True
                    if obj:
                        try:
                            container = obj.parent
                            is_new = False
                        except:
                            pass
                    
                    if container not in native_batches:
                        native_batches[container] = []
                    native_batches[container].append((
                        rel_path, abs_path, item.get("name", os.path.basename(rel_path)),
                        item.get("type_guid"), is_new
                    ))
                    continue
                
                # ST files: find or create
                obj = item.get("obj")
                if not obj:
                    obj = find_object_by_path(rel_path, primary_project)
                
                if obj:
                    # UPDATE — force=True because we already confirmed disk is different
                    obj_info = objects_meta.get(rel_path, {})
                    if not obj_info.get("type"):
                        obj_info["type"] = item.get("type_guid", "")
                    
                    if update_existing_object(obj, rel_path, abs_path, obj_info,
                                              import_managers, force=True):
                        update_object_metadata(objects_meta, rel_path, obj, abs_path, import_managers)
                        updated_count += 1
                        print("  Updated: " + rel_path)
                        log_info("Updated " + item["name"])
                else:
                    # CREATE
                    res = create_new_object(
                        rel_path, abs_path, import_managers, name_map,
                        folder_cache, primary_project, objects_meta
                    )
                    if res:
                        created_count += 1
                        print("  Created: " + rel_path)
                    else:
                        failed_count += 1
                    
            except Exception as e:
                log_error("Failed to import " + item.get("path", "unknown") + ": " + safe_str(e))
                failed_count += 1

        # Process batched XML imports
        if native_batches:
            u, c, f = batch_import_native_xmls(
                native_batches, import_managers, objects_meta, primary_project
            )
            updated_count += u
            created_count += c
            failed_count += f

        # Save metadata & project
        projects_obj = resolve_projects(None, globals())
        finalize_import(base_dir, metadata, primary_project, projects_obj,
                        updated_count, created_count)

    return updated_count, created_count, failed_count


def import_project(projects_obj=None, silent=False):
    """
    Main import entry point.
    Compares disk with IDE and imports all disk-side changes automatically.
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
    
    # Phase 1: Find all disk changes
    print("Comparing IDE with disk...")
    disk_modified, deleted_from_ide, unchanged_count = find_disk_changes(
        base_dir, projects_obj, metadata
    )
    
    print("")
    print("Changes found:")
    print("  Modified on disk: " + str(len(disk_modified)))
    print("  Deleted from IDE: " + str(len(deleted_from_ide)))
    print("  Unchanged: " + str(unchanged_count))
    
    if not disk_modified:
        elapsed = time.time() - start_time
        msg = "No disk changes to import.\nAll " + str(unchanged_count) + " objects are in sync."
        print(msg)
        if not silent:
            system.ui.info(msg + "\nTime: {:.2f}s".format(elapsed))
        return
    
    # Show what we're about to import
    print("")
    print("Importing " + str(len(disk_modified)) + " disk changes to IDE:")
    for item in disk_modified:
        print("  <- " + item["path"] + " (" + item["type"] + ")")
    
    # Phase 2: Import all disk changes
    updated, created, failed = perform_import(
        projects_obj.primary, base_dir, disk_modified, metadata
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

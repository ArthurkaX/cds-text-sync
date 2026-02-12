# -*- coding: utf-8 -*-
"""
Project_import.py - Import edited ST files back into CODESYS project

Reads _metadata.json to match files to CODESYS objects by GUID, then updates
the textual declaration and implementation from the ST files.

Usage: Run from CODESYS IDE after setting sync directory with Project_directory.py
 and editing files
"""
import os
import codecs
import json
import time
import re
from codesys_constants import IMPL_MARKER, TYPE_GUIDS
from codesys_utils import (
    safe_str, parse_st_file, build_object_cache, 
    find_object_by_guid, find_object_by_name, load_base_dir,
    calculate_hash, save_metadata, load_metadata,
    format_st_content, log_info, log_warning, log_error, MetadataLock,
    load_libraries, extract_libraries_from_project,
    init_logging, get_project_prop, backup_project_binary
)

# Shared constants and utilities imported from modules





def update_object_code(obj, declaration, implementation):
    """
    Update object's textual declaration and/or implementation.
    Returns True if any update was made.
    """
    updated = False
    obj_name = safe_str(obj.get_name())
    
    # Update declaration
    if declaration:
        try:
            if hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
                obj.textual_declaration.replace(declaration)
                updated = True
            else:
                log_warning(obj_name + " has no textual declaration property")
        except Exception as e:
            log_error("Error updating declaration for " + obj_name + ": " + safe_str(e))
    
    # Update implementation
    if implementation:
        try:
            if hasattr(obj, "has_textual_implementation") and obj.has_textual_implementation:
                obj.textual_implementation.replace(implementation)
                updated = True
            else:
                # This is normal for GVLs and DUTs - they only have declaration
                pass
        except Exception as e:
            log_error("Error updating implementation for " + obj_name + ": " + safe_str(e))
    
    return updated





def determine_object_type(content):
    """Determine CODESYS object type from ST content"""
    # Remove comments and pragmas to avoid false matches
    
    # 1. Remove (* ... *) multiline comments
    content = re.sub(r"\(\*[\s\S]*?\*\)", "", content)
    
    # 2. Remove { ... } pragmas/attributes
    content = re.sub(r"\{[\s\S]*?\}", "", content)
    
    # 3. Remove // ... single line comments
    content = re.sub(r"//.*", "", content)
    
    content = content.strip()
    lines = content.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check keywords
        parts = line.split()
        if not parts:
            continue
        word = parts[0].upper()
        
        if word == "PROGRAM":
            return TYPE_GUIDS["pou"]
        if word == "FUNCTION_BLOCK":
            return TYPE_GUIDS["pou"]
        if word == "FUNCTION":
            return TYPE_GUIDS["pou"]
        if word == "VAR_GLOBAL":
            return TYPE_GUIDS["gvl"]
        if word == "TYPE":
            return TYPE_GUIDS["dut"]
        if word == "INTERFACE":
            return TYPE_GUIDS["itf"]
        if word == "METHOD":
            return TYPE_GUIDS["method"]
        if word == "PROPERTY":
            return TYPE_GUIDS["property"]
        if word == "ACTION":
            return TYPE_GUIDS["action"]
        
    return None


# Global cache for start_obj to avoid repetitive searches and logging
_ensure_folder_start_obj = None

def ensure_folder_path(path_str):
    """
    Ensure folder structure exists in CODESYS project.
    path_str: relative path string e.g. "Folder/SubFolder"
    Returns the parent object (folder) or None if failed.
    """
    global _ensure_folder_start_obj
    
    if _ensure_folder_start_obj is None:
        def find_application_recursive(obj, depth=0):
            """Recursively search for Application or PLC Logic container"""
            if depth > 3:  # Limit recursion depth
                return None
                
            try:
                children = obj.get_children()
                for child in children:
                    try:
                        child_type = safe_str(child.type)
                        if child_type == TYPE_GUIDS["application"]:
                            return child
                        if child_type == TYPE_GUIDS["device"] or child_type == TYPE_GUIDS["plc_logic"]:
                            result = find_application_recursive(child, depth + 1)
                            if result:
                                return result
                    except:
                        continue
            except:
                pass
            return None

        try:
            start_obj = find_application_recursive(projects.primary, 0)
            if start_obj:
                _ensure_folder_start_obj = start_obj
                try:
                    container_name = safe_str(start_obj.get_name())
                    container_type = safe_str(start_obj.type)
                    print("  >>> Using container: " + container_name + " (type: " + container_type + ")")
                except:
                    print("  >>> Found container")
        except Exception as e:
            print("  Error getting project children: " + safe_str(e))

    start_obj = _ensure_folder_start_obj
    
    # Fallback to primary project if we can't find Application
    if start_obj is None:
        if _ensure_folder_start_obj is None: # Only warn once
            print("  Warning: Could not find Application/PLC Logic container, using project root")
            _ensure_folder_start_obj = projects.primary
        start_obj = _ensure_folder_start_obj
    
    if not path_str or path_str == ".":
        return start_obj
        
    parts = path_str.replace("\\", "/").split("/")
    current_obj = start_obj
    
    for part in parts:
        if not part: continue
        
        matches = []
        try:
            children = current_obj.get_children()
        except:
            children = []
            
        for child in children:
            if child.get_name().lower() == part.lower():
                try:
                    child_type = safe_str(child.type)
                    if child_type == TYPE_GUIDS["device"]:
                        continue 
                except:
                    pass
                matches.append(child)
        
        found = None
        
        if len(matches) > 1:
            print("  Found " + str(len(matches)) + " match(es) for '" + part + "' (Ambiguity):")
            for m in matches:
                try:
                    m_type = safe_str(m.type)
                    m_name = safe_str(m.get_name())
                    print("    - " + m_name + " (type: " + m_type + ")")
                except:
                    pass
        
        for m in matches:
            try:
                obj_type = safe_str(m.type)
                if obj_type == TYPE_GUIDS["folder"]:
                    found = m
                    break
            except:
                pass
                
        if not found:
            for m in matches:
                if hasattr(m, "create_child"):
                    found = m
                    break
                    
        if not found and matches:
             found = matches[0]

        if found:
            current_obj = found
        else:
            try:
                parent_obj = current_obj
                current_obj = None
                
                if hasattr(parent_obj, "create_folder"):
                    try:
                        current_obj = parent_obj.create_folder(part)
                    except Exception as e:
                        pass
                        
                if not current_obj and hasattr(parent_obj, "create_child"):
                    try:
                        current_obj = parent_obj.create_child(part, "738bea1e-99bb-4f04-90bb-a7a567e74e3a") 
                    except Exception as e:
                         pass
                         
                if not current_obj:
                    try:
                        children = parent_obj.get_children()
                        for child in children:
                            if child.get_name().lower() == part.lower():
                                current_obj = child
                                break
                    except:
                        pass

                if not current_obj:
                    return None
            except Exception as e:
                print("  Error creating folder " + part + ": " + safe_str(e))
                return None
                
    return current_obj


def cleanup_ide_orphans(import_dir, objects_meta, guid_map, name_map):
    """
    Find objects in IDE that have no corresponding file on disk and ask to delete them.
    Returns list of rel_paths that were deleted.
    """
    orphans = []
    # Sort by depth (number of slashes) and then by length to ensure children 
    # (longer names like Parent.Method) are processed before parents.
    all_paths = sorted(objects_meta.keys(), key=lambda x: (x.count('/'), len(x)), reverse=True)
    
    for rel_path in all_paths:
        file_path = os.path.join(import_dir, rel_path.replace("/", os.sep))
        if not os.path.exists(file_path):
            info = objects_meta[rel_path]
            
            # Debug: Log methods being considered for deletion
            if info.get("type") == TYPE_GUIDS["method"]:
                print("DEBUG: Method file not found, marking as orphan: " + rel_path)
                print("DEBUG: Expected file path: " + file_path)
            
            obj = None
            if info.get("guid") and info.get("guid") != "N/A":
                obj = find_object_by_guid(info["guid"], guid_map)
            
            if not obj and info.get("name"):
                obj = find_object_by_name(info["name"], name_map, info.get("parent"))
                
            if obj:
                orphans.append((rel_path, obj))

    if not orphans:
        return []

    message = "The following objects were removed from the disk but still exist in CODESYS:\n\n"
    for rel_path, _ in orphans[:15]:
        message += "- " + rel_path + "\n"
    
    message += "\nWould you like to delete these objects from the CODESYS project?"
    
    try:
        result = system.ui.choose(message, ("Delete from IDE", "Ignore", "Cancel Import"))
    except:
        return []
    
    if result[0] == 0:
        deleted_paths = []
        for rel_path, obj in orphans:
            try:
                # Check if object still exists and has a parent (not already removed)
                if obj and hasattr(obj, "get_name"):
                    try:
                        _ = obj.guid # Trigger access check
                    except:
                        # Object became invalid (probably parent was deleted)
                        continue
                        
                    obj.remove()
                    deleted_paths.append(rel_path)
            except Exception as e:
                # Ignore "Object reference not set" which often means already deleted
                if "Object reference not set" not in safe_str(e):
                    print("Error deleting " + rel_path + ": " + safe_str(e))
                else:
                    # Successfully "deleted" (effectively)
                    deleted_paths.append(rel_path)
        return deleted_paths
    elif result[0] == 1:
        return []
    else:
        return None 


def sync_libraries(import_dir):
    """
    Check libraries in project against _libraries.csv and warn about differences.
    Note: Automatic library updates are not reliable across all CODESYS versions.
    """
    libraries_file = load_libraries(import_dir)
    if not libraries_file:
        return
        
    print("  Checking project libraries...")
    
    # Get current project libraries
    current_libs = extract_libraries_from_project(projects.primary)
    
    if not current_libs:
        print("  Warning: Could not extract current library information")
        return
    
    # Compare
    missing_libs = []
    mismatch_libs = []
    
    for lib_file in libraries_file:
        found = False
        for lib_proj in current_libs:
            # Match by name or namespace to be robust
            if lib_file["name"] == lib_proj["name"] or (lib_file["namespace"] != "N/A" and lib_file["namespace"] == lib_proj["namespace"]):
                found = True
                if lib_file["version"] != lib_proj["version"]:
                    mismatch_libs.append((lib_file, lib_proj))
                break
        if not found:
            missing_libs.append(lib_file)
            
    if not missing_libs and not mismatch_libs:
        print("  All libraries match.")
        return
        
    # Show status
    message = "Library differences detected (Version Control):\n\n"
    if missing_libs:
        message += "Missing in CODESYS project:\n"
        for lib in missing_libs:
            message += "- " + lib["name"] + " (" + lib["version"] + ")\n"
        message += "\n"
        
    if mismatch_libs:
        message += "Version differences:\n"
        for lib_file, lib_proj in mismatch_libs:
            message += "- " + lib_file["name"] + ":\n    On disk: " + lib_file["version"] + "\n    In IDE:   " + lib_proj["version"] + "\n"
            
    message += "\nPlease update libraries manually via Library Manager.\n"
    message += "Would you like to continue with import?"
    
    try:
        result = system.ui.choose(message, ("Continue Import", "Cancel Import"))
    except:
        return
        
    if result[0] == 1: # Cancel
        return "CANCEL"


def import_project(import_dir):
    """Import ST files from folder structure back into CODESYS project"""
    
    if not projects.primary:
        system.ui.error("No project open!")
        return
    
    # Check save setting
    should_save = get_project_prop("cds-sync-save-after-import", True)
    
    print("=== Starting Project Import ===")
    print("Import directory: " + import_dir)
    print("Auto-save enabled: " + str(should_save))
    start_time = time.time()
    
    # Find Application container early
    app_container = None
    
    def find_application_recursive(obj, depth=0):
        if depth > 3:
            return None
        try:
            children = obj.get_children()
            for child in children:
                try:
                    child_type = safe_str(child.type)
                    if child_type == TYPE_GUIDS["application"]:
                        return child
                    if child_type == TYPE_GUIDS["device"] or child_type == TYPE_GUIDS["plc_logic"]:
                        result = find_application_recursive(child, depth + 1)
                        if result:
                            return result
                except:
                    continue
        except:
            pass
        return None
    
    try:
        app_container = find_application_recursive(projects.primary, 0)
    except:
        pass
    
    with MetadataLock(import_dir, timeout=60):
        # Load metadata
        metadata = load_metadata(import_dir)
        if not metadata:
            system.ui.error("Metadata not found!\n\nPlease run Project_export.py first.")
            return
        
        objects_meta = metadata.get("objects", {})
        print("  Loaded " + str(len(objects_meta)) + " objects from metadata")
        
        # Build cache
        print("  Building object cache...")
        guid_map, name_map = build_object_cache(projects.primary)
        print("  Cache built: " + str(len(guid_map)) + " objects by GUID")
        
        # Cleanup IDE orphans
        deleted_from_ide = cleanup_ide_orphans(import_dir, objects_meta, guid_map, name_map)
        if deleted_from_ide is None:
            return 
        
        for path in deleted_from_ide:
            if path in objects_meta:
                del objects_meta[path]
        
        # Sync libraries first
        if sync_libraries(import_dir) == "CANCEL":
            print("Import cancelled during library sync.")
            return
                
        # Track existing folders
        tracked_folders = set()
        for rel_path in objects_meta.keys():
            parts = rel_path.split("/")
            for i in range(1, len(parts)):
                tracked_folders.add("/".join(parts[:i]))
        
        # Identify new files and folders
        new_files = []
        new_folders = []
        
        for root, dirs, files in os.walk(import_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for d in dirs:
                 rel_path = os.path.relpath(os.path.join(root, d), import_dir).replace(os.sep, "/")
                 if rel_path not in objects_meta and rel_path not in tracked_folders:
                     new_folders.append(rel_path)
            
            for name in files:
                if name in ["_metadata.json", "_config.json", "_metadata.csv", "BASE_DIR", "sync_debug.log"] or name.startswith('.'):
                    continue
                if not name.endswith(".st"):
                    continue
                
                rel_path = os.path.relpath(os.path.join(root, name), import_dir).replace(os.sep, "/")
                if rel_path not in objects_meta:
                    new_files.append((rel_path, os.path.join(root, name)))
        
        updated_count = 0
        failed_count = 0
        skipped_count = 0
        created_count = 0
        deleted_count = len(deleted_from_ide) if deleted_from_ide else 0
        folder_cache = {} # Shared cache for folder resolution during this import
        
        # Update existing objects
        for rel_path, obj_info in objects_meta.items():
            file_path = os.path.join(import_dir, rel_path.replace("/", os.sep))
            if not os.path.exists(file_path):
                skipped_count += 1
                continue

            if obj_info.get("type") == TYPE_GUIDS["folder"] or os.path.isdir(file_path):
                continue
            
            obj = None
            if obj_info.get("guid") and obj_info.get("guid") != "N/A":
                obj = find_object_by_guid(obj_info["guid"], guid_map)
                
                # Debug: Log method lookups
                if obj_info.get("type") == TYPE_GUIDS["method"]:
                    if obj:
                        print("DEBUG: Found method by GUID: " + rel_path)
                    else:
                        print("DEBUG: Method NOT found by GUID: " + rel_path + " (GUID: " + obj_info["guid"] + ")")
                        print("DEBUG: guid_map has " + str(len(guid_map)) + " entries")
            
            if obj is None and obj_info.get("name"):
                obj = find_object_by_name(obj_info["name"], name_map, obj_info.get("parent"))
                
                # Debug: Log method name lookups
                if obj_info.get("type") == TYPE_GUIDS["method"]:
                    if obj:
                        print("DEBUG: Found method by name: " + rel_path)
                    else:
                        print("DEBUG: Method NOT found by name either: " + rel_path)
            
            if obj is None:
                # Debug: Log failed method lookups
                if obj_info.get("type") == TYPE_GUIDS["method"]:
                    print("DEBUG: Method lookup failed completely: " + rel_path)
                failed_count += 1
                continue
            
            # Optimization: Check timestamp first
            current_mtime = safe_str(os.path.getmtime(file_path))
            stored_mtime = obj_info.get("last_modified", "")
            stored_hash = obj_info.get("content_hash", "")
            
            if current_mtime == stored_mtime and stored_hash:
                print("  Skipped: " + rel_path + " (Timestamp match)")
                skipped_count += 1
                continue
                
            declaration, implementation = parse_st_file(file_path)
            if declaration is None and implementation is None:
                skipped_count += 1
                continue
                
            full_content = format_st_content(declaration, implementation)
            current_hash = calculate_hash(full_content)
            
            if current_hash == stored_hash:
                print("  Skipped: " + rel_path + " (Hash match, updating timestamp)")
                obj_info["last_modified"] = current_mtime
                skipped_count += 1
                continue
            
            print("  Updating: " + rel_path + " (Change detected)")
            if update_object_code(obj, declaration, implementation):
                updated_count += 1
                obj_info["content_hash"] = current_hash
                obj_info["last_modified"] = current_mtime
            else:
                print("  Warning: No changes applied to " + rel_path)
                skipped_count += 1
                
        # Process new folders
        if new_folders:
            new_folders.sort(key=len)
            for folder_path in new_folders:
                # Only process folders in src directory
                if not folder_path.startswith("src"):
                    continue
                if folder_path == "src":
                    continue
                    
                # Calculate CODESYS path (remove src prefix)
                codesys_path = folder_path[4:] if folder_path.startswith("src/") else ""
                
                if folder_path in folder_cache:
                    created_folder = folder_cache[folder_path]
                else:
                    created_folder = ensure_folder_path(codesys_path)
                    folder_cache[folder_path] = created_folder
                    
                if created_folder:
                    created_count += 1
                    objects_meta[folder_path] = {
                        "guid": safe_str(created_folder.guid),
                        "type": TYPE_GUIDS["folder"],
                        "name": safe_str(created_folder.get_name()),
                        "parent": safe_str(created_folder.parent.get_name()) if created_folder.parent else "N/A",
                        "content_hash": ""
                    }

        # Process new files
        if new_files:
            parent_ops = []
            child_ops = []
            
            for rel_path, file_path in new_files:
                 # Only process files in src directory
                 if not rel_path.startswith("src/"):
                     continue
                 
                 declaration, implementation = parse_st_file(file_path)
                 content_check = declaration if declaration else implementation
                 if not content_check:
                    skipped_count += 1
                    continue
                    
                 type_guid = determine_object_type(content_check)
                 # Strip src/ prefix for path parsing
                 filesys_path_parts = rel_path.split("/")
                 if filesys_path_parts[0] == "src":
                     path_parts = filesys_path_parts[1:]
                 else:
                     path_parts = filesys_path_parts
                     
                 base_name = os.path.splitext(path_parts[-1])[0]
                 
                 is_child = False
                 child_info = None

                 if not is_child:
                     upper_name = base_name.upper()
                     if upper_name.endswith(".GET"):
                         type_guid = TYPE_GUIDS["property_accessor"]
                         child_info = (base_name[:-4], "Get")
                         is_child = True
                     elif upper_name.endswith(".SET"):
                         type_guid = TYPE_GUIDS["property_accessor"]
                         child_info = (base_name[:-4], "Set")
                         is_child = True
                     elif base_name in ["Get", "Set"] and len(path_parts) > 1:
                         type_guid = TYPE_GUIDS["property_accessor"]
                         p_name = path_parts[-2]
                         child_info = (p_name, base_name)
                         is_child = True
                 
                 if not is_child and (not type_guid or type_guid in [TYPE_GUIDS["method"], TYPE_GUIDS["property"], TYPE_GUIDS["action"]]):
                     if "." in base_name:
                         parts = base_name.rsplit(".", 1)
                         child_info = (parts[0], parts[1])
                         is_child = True

                 op_data = {
                     "rel_path": rel_path, "file_path": file_path, "base_name": base_name,
                     "type_guid": type_guid, "declaration": declaration, "implementation": implementation,
                     "is_child": is_child, "child_info": child_info, "content_check": content_check
                 }
                 if is_child: 
                     child_ops.append(op_data)
                 else: 
                     parent_ops.append(op_data)
            
            print("  Found " + str(len(parent_ops)) + " new parent objects and " + str(len(child_ops)) + " new children")

            new_stats = {"updated": 0, "created": 0, "failed": 0, "skipped": 0}

            def process_op(op):
                type_guid = op["type_guid"]
                if not type_guid:
                    new_stats["skipped"] += 1
                    return

                create_container = None
                obj_name = op["base_name"]
                
                if op["is_child"] and op["child_info"]:
                    p_name, c_name = op["child_info"]
                    parent_obj = find_object_by_name(p_name, name_map)
                    if parent_obj: 
                        obj_name = c_name
                        create_container = parent_obj
                        print("  Identified parent " + p_name + " for new object " + c_name)
                    else:
                        print("  Error: Could not find parent " + p_name + " for new object " + c_name)
                else:
                    # New parent object - resolve folder path
                    rel_path = op["rel_path"] # e.g. src/Folder/POU.st
                    
                    if "/" in rel_path:
                        # logical_folder_path: src/Folder
                        logical_folder_path = "/".join(rel_path.split("/")[:-1])
                        
                        if logical_folder_path == "src":
                             create_container = app_container
                        elif logical_folder_path in folder_cache:
                            create_container = folder_cache[logical_folder_path]
                        else:
                            # Parse CODESYS path
                            codesys_path = logical_folder_path[4:] if logical_folder_path.startswith("src/") else logical_folder_path
                            create_container = ensure_folder_path(codesys_path)
                            folder_cache[logical_folder_path] = create_container
                    else:
                        create_container = app_container

                if not create_container:
                    print("  Error: Could not determine container for " + op["rel_path"])
                    new_stats["failed"] += 1
                    return

                obj = None
                try:
                    # Check existing
                    children = create_container.get_children()
                    for child in children:
                        if child.get_name().lower() == obj_name.lower():
                            obj = child
                            break
                    
                    if not obj:
                        if op["type_guid"] == TYPE_GUIDS["gvl"] and hasattr(create_container, "create_gvl"):
                            obj = create_container.create_gvl(obj_name)
                        elif op["type_guid"] == TYPE_GUIDS["dut"] and hasattr(create_container, "create_dut"):
                            obj = create_container.create_dut(obj_name)
                        elif op["type_guid"] == TYPE_GUIDS["method"] and hasattr(create_container, "create_method"):
                            obj = create_container.create_method(obj_name)
                        elif op["type_guid"] == TYPE_GUIDS["property"] and hasattr(create_container, "create_property"):
                            obj = create_container.create_property(obj_name)
                        elif op["type_guid"] == TYPE_GUIDS["action"] and hasattr(create_container, "create_action"):
                            obj = create_container.create_action(obj_name)
                        elif op["type_guid"] == TYPE_GUIDS["property_accessor"]:
                            if obj_name.lower() == "get" and hasattr(create_container, "create_get_accessor"):
                                obj = create_container.create_get_accessor()
                            elif obj_name.lower() == "set" and hasattr(create_container, "create_set_accessor"):
                                obj = create_container.create_set_accessor()
                        elif hasattr(create_container, "create_pou"):
                             # Default to Program for general POU creation if type is unknown or pou
                             p_type = PouType.Program
                             obj = create_container.create_pou(obj_name, p_type)
                        elif hasattr(create_container, "create_child"):
                             obj = create_container.create_child(obj_name, op["type_guid"])
                    
                    if obj:
                        if update_object_code(obj, op["declaration"], op["implementation"]):
                             new_stats["updated"] += 1
                             new_stats["created"] += 1
                             
                             full_content = format_st_content(op["declaration"], op["implementation"])
                             objects_meta[op["rel_path"]] = {
                                "guid": safe_str(obj.guid), 
                                "type": op["type_guid"],  # FIX: Use op["type_guid"] instead of type_guid
                                "name": obj_name,
                                "parent": safe_str(obj.parent.get_name()) if obj.parent else "N/A",
                                "content_hash": calculate_hash(full_content)
                             }
                             if obj_name not in name_map: name_map[obj_name] = []
                             name_map[obj_name].append(obj)
                    else:
                        new_stats["failed"] += 1
                except:
                    new_stats["failed"] += 1

            for op in parent_ops: process_op(op)
            for op in child_ops: process_op(op)
            
            updated_count += new_stats["updated"]
            created_count += new_stats["created"]
            failed_count += new_stats["failed"]
            skipped_count += new_stats["skipped"]
        
        if updated_count > 0 or created_count > 0 or (deleted_from_ide and len(deleted_from_ide) > 0):
            save_metadata(import_dir, metadata)
            
            # Check binary backup setting
            backup_binary = get_project_prop("cds-sync-backup-binary", False)

            # We must save if:
            # 1. User wants save after import (should_save)
            # 2. OR User wants binary backup (backup_binary) - because backup requires saved project
            must_save = should_save or backup_binary
            
            if must_save:
                try:
                    print("  Saving project...")
                    projects.primary.save()
                    
                    # After successful save, check if we need to update backup
                    if backup_binary:
                        print("  Updating binary backup...")
                        # Pass projects Explicitly
                        backup_project_binary(import_dir, projects)
                        
                except Exception as e:
                    print("  Warning: Could not save project: " + safe_str(e))
            else:
                print("  Skipping project save (user option).")
    
    print("=== Import Complete ===")
    print("  Updated: " + str(updated_count))
    print("  Created: " + str(created_count))
    print("  Deleted: " + str(deleted_count))
    print("  Failed:  " + str(failed_count))
    print("  Skipped: " + str(skipped_count))
    
    elapsed_time = time.time() - start_time
    print("  Time:    {:.2f}s".format(elapsed_time))
    
    log_info("Import complete! Updated: " + str(updated_count) + ", Created: " + str(created_count) + ", Deleted: " + str(deleted_count))
    
    # Check for silent mode (Non-Blocking UI)
    silent_mode = get_project_prop("cds-sync-silent-mode", False)
    
    if silent_mode:
        try:
            from codesys_ui import show_toast
            message = "Import Complete\nUpd: {}\nNew: {}\nDel: {}\nFail: {}\nTime: {:.2f}s".format(
                updated_count, created_count, deleted_count, failed_count, elapsed_time
            )
            show_toast("Import Complete", message)
        except:
            print("Import complete (Silent mode active, but UI module failed)")
    else:
        system.ui.info("Import complete!\n\nUpdated: " + str(updated_count) + "\nCreated: " + str(created_count) + "\nDeleted: " + str(deleted_count) + "\nFailed: " + str(failed_count) + "\nSkipped: " + str(skipped_count) + "\nTime: {:.2f}s".format(elapsed_time))


def main():
    base_dir, error = load_base_dir()
    if error:
        system.ui.warning(error)
        return
    
    message = "WARNING: This operation will overwrite CODESYS objects with data from the export directory.\n\nAre you sure you want to proceed?"
    
    try:
        result = system.ui.choose(message, ("Yes, Overwrite Data", "No, Cancel"))
    except:
        # Fallback for UI-less execution
        init_logging(base_dir)
        import_project(base_dir)
        return

    if result is None: # Dialog closed
        return
        
    if result[0] == 0: # Yes
        init_logging(base_dir)
        import_project(base_dir)


if __name__ == "__main__":
    main()

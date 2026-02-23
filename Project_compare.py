# -*- coding: utf-8 -*-
"""
Project_compare.py - Compare CODESYS project with disk files

Compares .st and .xml files between the CODESYS IDE and the sync folder to identify:
- Modified objects (content hash mismatch)
- New objects in IDE (not on disk)
- Deleted objects (on disk but not in IDE)

Outputs a concise git-style difference list and saves to compare.log.
"""
import os
import sys
import codecs
import time
import tempfile
from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES
from codesys_utils import (
    safe_str, load_base_dir, load_metadata, build_object_cache,
    calculate_hash, format_st_content, init_logging, log_info,
    get_project_prop, format_property_content, resolve_projects,
    clean_filename
)
from codesys_managers import (
    get_object_path, get_container_prefix, get_parent_pou_name,
    export_object_content, collect_property_accessors, is_nvl,
    NativeManager
)

# Reverse mapping for friendly type names
TYPE_NAMES = {v: k for k, v in TYPE_GUIDS.items()}


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
    
    # Track which disk paths we've matched to IDE objects
    matched_disk_paths = set()
    
    # First pass: collect property accessors
    property_accessors = collect_property_accessors(all_ide_objects)
    
    # NativeManager for consistent XML hash comparison
    native_mgr = NativeManager()    
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
            
            # Determine effective type (detect NVLs hiding as GVLs)
            effective_type = obj_type
            is_xml_object = False
            
            if obj_type == TYPE_GUIDS["gvl"]:
                try:
                    if is_nvl(obj):
                        effective_type = TYPE_GUIDS["nvl_sender"]
                        is_xml_object = True
                except:
                    pass
            
            # Check if this is an XML type
            if effective_type in XML_TYPES:
                is_xml_object = True
                # Respect the same export_xml gate as Project_export.py
                # Only task_config and NVL types are always exported
                if not metadata.get("export_xml", False) and effective_type not in [TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]]:
                    continue
                
            # Only process exportable types
            if effective_type not in EXPORTABLE_TYPES and effective_type not in XML_TYPES:
                continue
            
            # Build expected file path
            container = get_container_prefix(obj)
            path_parts = get_object_path(obj)
            clean_name = clean_filename(obj_name)
            
            if is_xml_object:
                # XML objects
                file_name = clean_name + ".xml"
            else:
                # ST objects - handle nested objects (actions, methods, properties)
                parent_pou = get_parent_pou_name(obj)
                if parent_pou and obj_type in [TYPE_GUIDS["action"], TYPE_GUIDS["method"], TYPE_GUIDS["property"]]:
                    file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
                    clean_parent_pou = clean_filename(parent_pou)
                    if path_parts and path_parts[-1] == clean_parent_pou:
                        path_parts = path_parts[:-1]
                else:
                    file_name = clean_name + ".st"
            
            # Build relative path
            full_path_parts = container + path_parts
            if full_path_parts:
                rel_path = "/".join(full_path_parts) + "/" + file_name
            else:
                rel_path = file_name
            
            # Get type name for display
            type_name = TYPE_NAMES.get(effective_type, effective_type[:8])
            
            # Compare content
            if rel_path in disk_objects:
                matched_disk_paths.add(rel_path)
                disk_info = disk_objects[rel_path]
                meta_hash = disk_info.get("content_hash", "")
                
                if is_xml_object:
                    # For XML objects, use NativeManager._hash_file for consistent hashing
                    file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                    if os.path.exists(file_path):
                        current_hash = native_mgr._hash_file(file_path)
                        if current_hash and current_hash != meta_hash:
                            modified.append({
                                "name": obj_name,
                                "path": rel_path,
                                "type": type_name,
                                "type_guid": effective_type,
                                "direction": "disk",
                                "obj": obj
                            })
                        else:
                            unchanged.append(rel_path)
                    else:
                        # File in metadata but missing from disk
                        new_in_ide.append({
                            "name": obj_name,
                            "path": rel_path,
                            "type": type_name,
                            "type_guid": effective_type,
                            "obj": obj
                        })
                else:
                    # ST content comparison (three-way: IDE vs metadata vs disk)
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
                        # Check textual content exists
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
                            unchanged.append(rel_path)
                            continue
                        
                        declaration, implementation = export_object_content(obj)
                        ide_content = format_st_content(declaration, implementation)
                    
                    if not ide_content or not ide_content.strip():
                        unchanged.append(rel_path)
                        continue
                    
                    ide_hash = calculate_hash(ide_content)
                    
                    # Read the actual disk file hash
                    disk_file_hash = ""
                    file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                    if os.path.exists(file_path):
                        try:
                            with codecs.open(file_path, "r", "utf-8") as df:
                                disk_content = df.read()
                            disk_file_hash = calculate_hash(disk_content)
                        except:
                            pass
                    
                    # Three-way comparison
                    ide_changed = (ide_hash != meta_hash)
                    disk_changed = (disk_file_hash != "" and disk_file_hash != meta_hash)
                    
                    if ide_changed and disk_changed:
                        modified.append({
                            "name": obj_name,
                            "path": rel_path,
                            "type": type_name,
                            "type_guid": effective_type,
                            "direction": "both",
                            "obj": obj
                        })
                    elif ide_changed:
                        modified.append({
                            "name": obj_name,
                            "path": rel_path,
                            "type": type_name,
                            "type_guid": effective_type,
                            "direction": "ide",
                            "obj": obj
                        })
                    elif disk_changed:
                        modified.append({
                            "name": obj_name,
                            "path": rel_path,
                            "type": type_name,
                            "type_guid": effective_type,
                            "direction": "disk",
                            "obj": obj
                        })
                    else:
                        unchanged.append(rel_path)
            else:
                # Object exists in IDE but not in metadata
                if is_xml_object:
                    # For XML objects, only report as new if the file actually exists on disk
                    # (export may silently fail for some container types)
                    file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                    if not os.path.exists(file_path):
                        continue
                else:
                    # For ST objects, check has content
                    has_content = False
                    try:
                        if hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
                            has_content = True
                        if hasattr(obj, "has_textual_implementation") and obj.has_textual_implementation:
                            has_content = True
                    except:
                        pass
                    is_property = obj_type == TYPE_GUIDS["property"]
                    if is_property and obj_guid in property_accessors:
                        has_content = True
                    if not has_content:
                        continue
                
                new_in_ide.append({
                    "name": obj_name,
                    "path": rel_path,
                    "type": type_name,
                    "type_guid": effective_type,
                    "obj": obj
                })
        
        except Exception as e:
            print("Error processing object: " + safe_str(e))
            continue
    
    # Third pass: Find objects on disk that don't exist in IDE
    for rel_path, disk_info in disk_objects.items():
        # Skip folders
        if disk_info.get("type") == TYPE_GUIDS["folder"]:
            continue
        # Only consider .st and .xml files
        if not rel_path.endswith(".st") and not rel_path.endswith(".xml"):
            continue
        
        # Skip already matched
        if rel_path in matched_disk_paths:
            continue
        
        # Skip unchanged (matched in pass 2)
        if rel_path in unchanged:
            continue
            
        # Check if already counted as modified or new
        already_counted = False
        for item in modified + new_in_ide:
            if item["path"] == rel_path:
                already_counted = True
                break
        
        if already_counted:
            continue
        
        obj_name = disk_info.get("name", os.path.basename(rel_path))
        obj_type_guid = disk_info.get("type", "unknown")
        type_name = TYPE_NAMES.get(obj_type_guid, obj_type_guid[:8] if len(obj_type_guid) > 8 else obj_type_guid)
        
        deleted_from_ide.append({
            "name": obj_name,
            "path": rel_path,
            "type": type_name,
            "type_guid": obj_type_guid
        })
    
    # Generate report - git-style concise output
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
    
    print("")
    if diff_lines:
        print("CHANGES:")
        for line in diff_lines:
            print(line)
    else:
        print("No differences found - IDE and disk are in sync!")
    
    print("")
    print("Summary: M:" + str(len(modified)) + " +:" + str(len(new_in_ide)) + " -:" + str(len(deleted_from_ide)) + " =:" + str(len(unchanged)) + " | {:.2f}s".format(elapsed))
    
    # Log to sync_debug.log
    log_info("COMPARE: M:" + str(len(modified)) + " +:" + str(len(new_in_ide)) + " -:" + str(len(deleted_from_ide)) + " =:" + str(len(unchanged)))
    if diff_lines:
        log_info("DIFF:\n" + "\n".join(diff_lines))
    
    # Show summary dialog
    if not silent:
        if not diff_lines:
            system.ui.info("IDE and Disk are in sync!\n\nObjects checked: " + str(len(unchanged)))
        else:
            # Group modified by direction
            ide_changes = [m for m in modified if m.get("direction") == "ide"]
            disk_changes = [m for m in modified if m.get("direction") == "disk"]
            both_changes = [m for m in modified if m.get("direction") == "both"]
            other_changes = [m for m in modified if m.get("direction") not in ("ide", "disk", "both")]
            # Merge other into disk
            all_disk = disk_changes + other_changes
            
            # Show WinForms dialog with checkboxes
            from codesys_ui import show_compare_dialog
            action, selected = show_compare_dialog(
                ide_changes, all_disk, both_changes,
                new_in_ide, deleted_from_ide, len(unchanged)
            )
            
            if action == "import":
                perform_import(projects_obj.primary, base_dir, selected, deleted_from_ide, metadata)
            elif action == "export":
                perform_export(base_dir, selected, new_in_ide, metadata)


def perform_import(primary_project, base_dir, modified, deleted_from_ide, metadata):
    """Trigger native import for disk-side changes, mirroring Project_import.py logic"""
    xml_files = []
    
    # Collect files to import
    # If the user clicked "Import", we process everything selected that exists on disk
    to_sync = modified
    
    if not to_sync:
        system.ui.info("No files selected for import.")
        return

    from codesys_managers import FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager, update_object_code
    from codesys_utils import (
        parse_st_file, parse_property_content, find_object_by_path, 
        build_object_cache, ensure_folder_path, determine_object_type,
        find_object_by_name, save_metadata, MetadataLock, backup_project_binary
    )
    
    # Initialize managers (same as Project_import.py)
    import_managers = {
        TYPE_GUIDS["folder"]: FolderManager(),
        TYPE_GUIDS["property"]: PropertyManager(),
        TYPE_GUIDS["task_config"]: ConfigManager(),
        "default": POUManager(),
        "native": NativeManager()
    }
    
    # Build cache once
    guid_map, name_map = build_object_cache(primary_project)
    objects_meta = metadata.get("objects", {})
    folder_cache = {}
    
    updated_count = 0
    created_count = 0
    failed_count = 0
    
    with MetadataLock(base_dir, timeout=60):
        for item in to_sync:
            try:
                rel_path = item["path"]
                abs_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                
                if not os.path.exists(abs_path):
                    continue
                    
                # Handle XML files (batch later)
                if rel_path.endswith(".xml"):
                    xml_files.append((rel_path, abs_path, item))
                    continue
                    
                # Handle ST files
                obj = item.get("obj")
                if not obj:
                    obj = find_object_by_path(rel_path, primary_project)
                
                # Resolve manager
                obj_type = item.get("type_guid") # We might need to handle names vs guids
                # For safety, determine from content or use item['type'] name mapping
                
                if obj:
                    # UPDATE existing object
                    # Force update by ignoring disk-metadata check (IDE is different, so we want disk content)
                    meta_item = objects_meta.get(rel_path, {})
                    temp_info = meta_item.copy()
                    temp_info["content_hash"] = "FORCE_SYNC" # Ensure hash mismatch to trigger update
                    
                    # Resolve manager
                    type_guid = item.get("type_guid")
                    manager = import_managers.get(type_guid, import_managers["default"])
                    if item.get("type") == "property": manager = import_managers[TYPE_GUIDS["property"]]
                    
                    if manager.update(obj, abs_path, temp_info):
                        if rel_path in objects_meta:
                            objects_meta[rel_path].update(temp_info)
                        updated_count += 1
                        log_info("Updated " + item["name"])
                else:
                    # CREATE new object
                    path_parts = rel_path.split("/")
                    
                    # 1. Ensure parent folder structure exists
                    if len(path_parts) > 1:
                        folder_path = "/".join(path_parts[:-1])
                        if folder_path in folder_cache:
                            container = folder_cache[folder_path]
                        else:
                            container = ensure_folder_path(folder_path, primary_project)
                            folder_cache[folder_path] = container
                    else:
                        container = primary_project
                        
                    if not container:
                        log_error("Could not find or create container for " + rel_path)
                        failed_count += 1
                        continue
                    
                    # 2. Determine type and name
                    base_name = os.path.splitext(path_parts[-1])[0]
                    decl, impl = parse_st_file(abs_path)
                    type_guid = determine_object_type(decl if decl else impl)
                    
                    # Handle nested objects (Action, Method, Property)
                    name = base_name
                    if "." in base_name and type_guid in [TYPE_GUIDS["action"], TYPE_GUIDS["method"], TYPE_GUIDS["property"]]:
                        parts = base_name.rsplit(".", 1)
                        parent_name = parts[0]
                        name = parts[1]
                        pou_parent = find_object_by_name(parent_name, name_map)
                        if pou_parent:
                            container = pou_parent
                    
                    # 3. Create via appropriate manager
                    manager = import_managers.get(type_guid, import_managers["default"])
                    res = manager.create(container, name, abs_path, type_guid)
                    if res:
                        created_count += 1
                        log_info("Created " + rel_path)
                        # Update metadata
                        objects_meta[rel_path] = {
                            "guid": safe_str(res.guid),
                            "type": safe_str(res.type),
                            "name": res.get_name(),
                            "parent": safe_str(res.parent.get_name()) if res.parent and hasattr(res.parent, 'get_name') else "N/A",
                            "content_hash": calculate_hash(codecs.open(abs_path, "r", "utf-8").read()) if not rel_path.endswith(".xml") else "",
                            "last_modified": safe_str(os.path.getmtime(abs_path))
                        }
                    else:
                        log_error("Failed to create " + rel_path)
                        failed_count += 1
                        
            except Exception as e:
                log_error("Failed to import " + item.get("path", "unknown") + ": " + safe_str(e))
                failed_count += 1

        # 1. Handle XML files (batch import)
        if xml_files:
            from codesys_utils import merge_native_xmls
            # Group by container if possible, but for simplicity we'll do one batch at project root
            # just like Project_import.py does for many cases
            tmp_xml = os.path.join(tempfile.gettempdir(), "cds_sync_merge.xml")
            abs_paths = [x[1] for x in xml_files]
            if merge_native_xmls(abs_paths, tmp_xml):
                try:
                    primary_project.import_native(tmp_xml)
                    log_info("Native XML import triggered for " + str(len(xml_files)) + " files.")
                    
                    # Post-import metadata update for XMLs
                    for rel_path, abs_path, item in xml_files:
                        obj = find_object_by_path(rel_path, primary_project)
                        if obj:
                            if rel_path not in objects_meta: created_count += 1
                            else: updated_count += 1
                            objects_meta[rel_path] = {
                                "guid": safe_str(obj.guid),
                                "type": safe_str(obj.type),
                                "name": obj.get_name(),
                                "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else "N/A",
                                "content_hash": import_managers["native"]._hash_file(abs_path),
                                "last_modified": safe_str(os.path.getmtime(abs_path))
                            }
                except Exception as e:
                    system.ui.error("Native import failed: " + safe_str(e))
                    failed_count += len(xml_files)
                finally:
                    if os.path.exists(tmp_xml):
                        try: os.remove(tmp_xml)
                        except: pass

        if updated_count > 0 or created_count > 0:
            save_metadata(base_dir, metadata)
            
            # Binary Backup handling (mirror Project_import.py)
            should_save = get_project_prop("cds-sync-save-after-import", True)
            backup_binary = get_project_prop("cds-sync-backup-binary", False)
            if should_save or backup_binary:
                try:
                    primary_project.save()
                    if backup_binary:
                        # Resolve projects object for backup
                        import sys
                        proj_obj = sys.modules.get('__main__')
                        backup_project_binary(base_dir, proj_obj)
                except: pass

    system.ui.info("Import complete!\n\nUpdated: {}\nCreated: {}\nFailed: {}".format(updated_count, created_count, failed_count))



def perform_export(base_dir, modified, new_in_ide, metadata):
    """Trigger export for IDE-side changes"""
    from codesys_managers import POUManager, NativeManager, ConfigManager, PropertyManager
    
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
        mgr = managers.get(obj_type, native_mgr)
        
        try:
            res = mgr.export(obj, context)
            if res: count += 1
        except Exception as e:
            log_error("Export failed for " + item["name"] + ": " + safe_str(e))
            
    # Save updated metadata
    from codesys_utils import save_metadata
    save_metadata(base_dir, metadata)
    
    system.ui.info("Exported " + str(count) + " objects.\nMetadata updated.")


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

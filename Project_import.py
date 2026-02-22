import os
import time
import codecs
import sys

# Force reload of shared modules to pick up latest changes
# (CODESYS caches modules in sys.modules across script runs)
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]
from codesys_constants import (
    IMPL_MARKER, TYPE_GUIDS, PROPERTY_GET_MARKER, PROPERTY_SET_MARKER, XML_TYPES
)
from codesys_utils import (
    safe_str, parse_st_file, build_object_cache, 
    find_object_by_guid, find_object_by_name, find_object_by_path, load_base_dir,
    load_metadata, save_metadata, merge_native_xmls,
    format_st_content, log_info, log_warning, log_error, MetadataLock,
    init_logging, get_project_prop, backup_project_binary,
    parse_property_content, format_property_content,
    ensure_folder_path, determine_object_type, resolve_projects,
    calculate_hash, update_application_count_flag
)
from codesys_managers import (
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    update_object_code
)

# Global cache for start_obj (legacy for internal use if needed)
_ensure_folder_start_obj = None

# Legacy support
def find_application_recursive(obj, depth=0):
    from codesys_utils import find_application_recursive as find_app
    return find_app(obj, depth)

def ensure_folder_path(path_str):
    from codesys_utils import ensure_folder_path as ensure_path
    # In CODESYS, 'projects' is a global object, no need to import it
    return ensure_path(path_str, projects.primary)


def cleanup_ide_orphans(import_dir, objects_meta, guid_map, name_map, silent=False):
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

    # Check for auto-delete property
    try:
        auto_delete = get_project_prop("cds-sync-auto-delete-orphans", False)
    except:
        auto_delete = False

    if silent:
        if auto_delete:
             result = (0,) # Simulate Delete
        else:
             print("Silent import: " + str(len(orphans)) + " objects need deletion but auto-delete is OFF.")
             return [] # Ignore
    else:
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


def import_project(import_dir, projects_obj=None, silent=False):
    """Import ST files from folder structure back into CODESYS project"""
    
    # Resolving projects object
    projects_obj = resolve_projects(projects_obj, globals())
    
    if projects_obj is None or not projects_obj.primary:
        error_msg = "Script Error: 'projects' object not found or no project open."
        if not silent:
            system.ui.error(error_msg)
        else:
            print(error_msg)
        return

    if not projects_obj.primary:
        if not silent:
            system.ui.error("No project open!")
        else:
            print("Error: No project open")
        return
    
    # Check save setting
    should_save = get_project_prop("cds-sync-save-after-import", True)
    
    print("=== Starting Project Import ===")
    update_application_count_flag()
    print("Import directory: " + import_dir)
    print("Auto-save enabled: " + str(should_save))
    start_time = time.time()

    # Timestamped Backup BEFORE import (New feature)
    # This creates a timestamped .bak file in the /project folder
    try:
        safety_backup = get_project_prop("cds-sync-safety-backup", True)
        if safety_backup:
            print("  Creating preliminary timestamped backup...")
            backup_project_binary(import_dir, projects_obj, timestamped=True)
    except Exception as e:
        print("  Warning: Could not create timestamped backup: " + safe_str(e))
    
    # Binary Backup handles safety
    
    # Initialize managers
    import_managers = {
        TYPE_GUIDS["folder"]: FolderManager(),
        TYPE_GUIDS["property"]: PropertyManager(),
        TYPE_GUIDS["task_config"]: ConfigManager(),
        "default": POUManager(),
        "native": NativeManager()
    }
    
    with MetadataLock(import_dir, timeout=60):
        # Load metadata
        metadata = load_metadata(import_dir)
        if not metadata:
            if not silent:
                system.ui.error("Metadata not found!\n\nPlease run Project_export.py first.")
            else:
                print("Error: Metadata not found")
            return
        
        objects_meta = metadata.get("objects", {})
        print("  Loaded " + str(len(objects_meta)) + " objects from metadata")
        
        # Build cache
        print("  Building object cache...")
        guid_map, name_map = build_object_cache(projects.primary)
        print("  Cache built: " + str(len(guid_map)) + " objects by GUID")
        
        # Cleanup IDE orphans
        deleted_from_ide = cleanup_ide_orphans(import_dir, objects_meta, guid_map, name_map, silent=silent)
        if deleted_from_ide is None:
            return 
        
        for path in deleted_from_ide:
            if path in objects_meta:
                del objects_meta[path]
        
                
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
                if not name.endswith(".st") and not name.endswith(".xml"):
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
        
        # Update/Create batches for Native imports to reduce dialogs
        # Format: { container_obj: [(rel_path, file_path, name, type_guid, is_new)] }
        native_batches = {}
        
        # Update existing objects
        for rel_path, obj_info in objects_meta.items():
            file_path = os.path.join(import_dir, rel_path.replace("/", os.sep))
            if not os.path.exists(file_path):
                skipped_count += 1
                continue

            obj_type = obj_info.get("type")
            
            # Skip property accessors - they are handled by PropertyManager
            if obj_type == TYPE_GUIDS.get("property_accessor"):
                continue

            obj = None
            guid_matched = False
            if obj_info.get("guid") and obj_info.get("guid") != "N/A":
                obj = find_object_by_guid(obj_info["guid"], guid_map)
                if obj:
                    guid_matched = True
            
            if obj is None and obj_info.get("name"):
                obj = find_object_by_name(obj_info["name"], name_map, obj_info.get("parent"))
                
                # Cross-validate: when GUID failed but name matched, verify using
                # the full hierarchical path. This prevents false matches when
                # identically-named objects exist under different applications
                # (e.g. DUTs in both ST_Application and LAD_Application).
                if obj and not guid_matched:
                    path_obj = find_object_by_path(rel_path, projects.primary)
                    if path_obj is None or (hasattr(path_obj, 'guid') and hasattr(obj, 'guid') 
                                            and safe_str(path_obj.guid) != safe_str(obj.guid)):
                        # Name matched a different object (from another Application)
                        # This is NOT the correct object - mark as not found
                        print("  Path validation: '" + rel_path + "' name-matched wrong object, will recreate")
                        obj = None
            
            if obj is None:
                # Final fallback: try to find by hierarchical path
                obj = find_object_by_path(rel_path, projects.primary)
            
            if obj is None:
                # Object not found - will recreate
                if obj_type == TYPE_GUIDS["folder"] or os.path.isdir(file_path):
                    if rel_path not in new_folders:
                        new_folders.append(rel_path)
                else:
                    if rel_path not in [nf[0] for nf in new_files]:
                        new_files.append((rel_path, file_path))
                continue

            # If object exists and is a folder, nothing left to do
            if obj_type == TYPE_GUIDS["folder"] or os.path.isdir(file_path):
                continue
            
            # Select manager
            manager = import_managers.get(obj_type)
            if not manager:
                if any(obj_type == guid for guid in XML_TYPES):
                    manager = import_managers["native"]
                else:
                    manager = import_managers["default"]
            
            if isinstance(manager, (NativeManager, ConfigManager)):
                try:
                    # Check if XML file has changed by comparing hash
                    stored_hash = obj_info.get("content_hash", "")
                    if stored_hash:
                        current_hash = import_managers["native"]._hash_file(file_path) if hasattr(import_managers["native"], '_hash_file') else ""
                        if current_hash and current_hash == stored_hash:
                            skipped_count += 1
                            continue
                    
                    # Collect for batch processing
                    try:
                        container = obj.parent
                    except:
                        container = projects.primary
                        
                    if container not in native_batches: native_batches[container] = []
                    native_batches[container].append((rel_path, file_path, obj_info.get("name", "Unknown"), obj_type, False))
                    continue
                except Exception as e:
                    log_error("Failed to batch " + rel_path + ": " + safe_str(e))
                    skipped_count += 1
                    continue

            try:
                if manager.update(obj, file_path, obj_info):
                    updated_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                log_error("Failed to update " + rel_path + ": " + safe_str(e))
                failed_count += 1
                
        # Process new folders
        if new_folders:
            new_folders.sort(key=len)
            folder_manager = import_managers[TYPE_GUIDS["folder"]]
            for folder_path in new_folders:
                # folders now have hierarchical paths, no 'src/' prefix check strictly needed
                # except to skip things like '.git' or 'project/' which are already filtered in os.walk
                res = folder_manager.create(None, None, folder_path, None)
                if res:
                    created_count += 1
                    objects_meta[folder_path] = {
                        "guid": safe_str(res.guid),
                        "type": TYPE_GUIDS["folder"],
                        "name": safe_str(res.get_name()),
                        "parent": safe_str(res.parent.get_name()) if res.parent and hasattr(res.parent, 'get_name') else "N/A",
                        "content_hash": ""
                    }

        # Process new files
        if new_files:
            new_files.sort(key=lambda x: (x[0].count('/'), x[0].count('.')))
            
            for rel_path, file_path in new_files:
                # Determine name and type
                path_parts = rel_path.split("/")
                base_name = os.path.splitext(path_parts[-1])[0]
                
                # Resolve type
                type_guid = None
                if rel_path.endswith(".xml"):
                    manager = import_managers["native"]
                else:
                    from codesys_utils import parse_st_file
                    decl, impl = parse_st_file(file_path)
                    content_check = decl if decl else impl
                    if not content_check:
                        skipped_count += 1
                        continue
                    
                    type_guid = determine_object_type(content_check)
                    manager = import_managers.get(type_guid, import_managers["default"])

                # Resolve container
                parent_name = None
                if "." in base_name and type_guid in [TYPE_GUIDS.get("method"), TYPE_GUIDS.get("property"), TYPE_GUIDS.get("action"), TYPE_GUIDS.get("property_accessor")]:
                    parts = base_name.rsplit(".", 1)
                    parent_name = parts[0]
                    name = parts[1]
                else:
                    name = base_name
                
                create_container = None
                if parent_name:
                    create_container = find_object_by_name(parent_name, name_map)
                
                if not create_container:
                     # Use hierarchical path to resolve container
                     if len(path_parts) > 1:
                         folder_path = "/".join(path_parts[:-1])
                         if folder_path in folder_cache:
                             create_container = folder_cache[folder_path]
                         else:
                             create_container = ensure_folder_path(folder_path)
                             folder_cache[folder_path] = create_container
                     else:
                         # Landing in project root (e.g. Project Settings)
                         create_container = projects.primary

                if not create_container:
                    log_error("Could not find or create container for " + rel_path)
                    failed_count += 1
                    continue
                
                if isinstance(manager, (NativeManager, ConfigManager)):
                    if create_container not in native_batches: native_batches[create_container] = []
                    native_batches[create_container].append((rel_path, file_path, name, type_guid, True))
                    continue

                try:
                    res = manager.create(create_container, name, file_path, type_guid)
                    if res:
                        created_count += 1
                        # Update metadata and cache
                        objects_meta[rel_path] = {
                            "guid": safe_str(res.guid),
                            "type": safe_str(res.type),
                            "name": res.get_name(),
                            "parent": safe_str(res.parent.get_name()) if res.parent and hasattr(res.parent, 'get_name') else "N/A",
                            "content_hash": calculate_hash(open(file_path, "rb").read().decode('utf-8')) if not rel_path.endswith(".xml") else "",
                            "last_modified": safe_str(os.path.getmtime(file_path))
                        }
                        if res.get_name() not in name_map: name_map[res.get_name()] = []
                        name_map[res.get_name()].append(res)
                    else:
                        failed_count += 1
                except Exception as e:
                    log_error("Failed to create " + rel_path + ": " + safe_str(e))
                    failed_count += 1
        
        # Process Native Batches (reduces dialogs from 15 to 1-2)
        if native_batches:
            for container, items in native_batches.items():
                print("  Batch importing " + str(len(items)) + " native objects into " + safe_str(container))
                temp_xml = os.path.join(import_dir, "batch_import_temp.xml")
                file_paths = [item[1] for item in items]
                
                if merge_native_xmls(file_paths, temp_xml):
                    try:
                        if hasattr(container, "import_native"):
                            container.import_native(temp_xml)
                        else:
                            projects.primary.import_native(temp_xml)
                        
                        # Cleanup
                        if os.path.exists(temp_xml): os.remove(temp_xml)
                        
                        # Resolve and metadata update
                        for rel_path, file_path, name, type_guid, is_new in items:
                            res = None
                            for child in container.get_children():
                                if child.get_name().lower() == name.lower():
                                    res = child
                                    break
                            
                            if res:
                                if is_new: created_count += 1
                                else: updated_count += 1
                                
                                objects_meta[rel_path] = {
                                    "guid": safe_str(res.guid),
                                    "type": safe_str(res.type),
                                    "name": res.get_name(),
                                    "parent": safe_str(res.parent.get_name()) if res.parent and hasattr(res.parent, 'get_name') else "N/A",
                                    "content_hash": "",
                                    "last_modified": safe_str(os.path.getmtime(file_path))
                                }
                            else:
                                log_error("Batch import could not find " + name + " after import.")
                                failed_count += 1
                                
                    except Exception as e:
                        log_error("Batch import failed for " + safe_str(container) + ": " + safe_str(e))
                        failed_count += len(items)
                else:
                    log_error("Failed to merge XML for " + safe_str(container))
                    failed_count += len(items)
        
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
                    projects_obj.primary.save()
                    
                    # After successful save, check if we need to update backup
                    if backup_binary:
                        print("  Updating binary backup...")
                        # Pass projects Explicitly
                        backup_project_binary(import_dir, projects_obj)
                        
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
    
    log_info("Import complete! Updated: " + str(updated_count) + ", Created: " + str(created_count) + ", Deleted: " + str(deleted_count) + ", Failed: " + str(failed_count) + ", Skipped: " + str(skipped_count))
    
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
    
    # Check if we are being run in silent mode (e.g. from Daemon)
    is_silent = globals().get("SILENT", False)
    
    if is_silent:
        print("Importing in silent mode (via Daemon)...")
        init_logging(base_dir)
        import_project(base_dir, silent=True)
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

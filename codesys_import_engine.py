# -*- coding: utf-8 -*-
"""
codesys_import_engine.py - Shared import logic for CODESYS synchronization

Extracted from Project_import.py and Project_compare.py to eliminate
duplication. Both scripts use this engine for the actual update/create
operations.
"""
import os
import codecs
import tempfile

from codesys_constants import TYPE_GUIDS, XML_TYPES
from codesys_utils import (
    safe_str, log_info, log_error, calculate_hash,
    parse_st_file, find_object_by_path, find_object_by_guid,
    find_object_by_name, build_object_cache, ensure_folder_path,
    determine_object_type, save_metadata, merge_native_xmls,
    get_project_prop, backup_project_binary, MetadataLock
)
from codesys_managers import (
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    update_object_code
)


def create_import_managers():
    """Create the standard manager dict used by both import paths."""
    return {
        TYPE_GUIDS["folder"]: FolderManager(),
        TYPE_GUIDS["property"]: PropertyManager(),
        TYPE_GUIDS["task_config"]: ConfigManager(),
        "default": POUManager(),
        "native": NativeManager()
    }


def resolve_manager(import_managers, type_guid, rel_path):
    """Pick the correct manager for a given type/path."""
    if rel_path.endswith(".xml"):
        return import_managers["native"]
    mgr = import_managers.get(type_guid)
    if not mgr:
        if type_guid in XML_TYPES:
            return import_managers["native"]
        return import_managers["default"]
    return mgr


def update_object_metadata(objects_meta, rel_path, obj, file_path, import_managers):
    """Write a consistent metadata entry after create/update."""
    is_xml = rel_path.endswith(".xml")
    content_hash = ""
    if is_xml:
        if hasattr(import_managers["native"], "_hash_file"):
            content_hash = import_managers["native"]._hash_file(file_path)
    else:
        try:
            from codesys_utils import parse_st_file, format_st_content
            declaration, implementation = parse_st_file(file_path)
            if declaration is not None or implementation is not None:
                full_content = format_st_content(declaration, implementation)
                content_hash = calculate_hash(full_content)
            else:
                with codecs.open(file_path, "r", "utf-8") as f:
                    content_hash = calculate_hash(f.read())
        except:
            pass

    objects_meta[rel_path] = {
        "guid": safe_str(obj.guid),
        "type": safe_str(obj.type),
        "name": obj.get_name(),
        "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else "N/A",
        "content_hash": content_hash,
        "last_modified": safe_str(os.path.getmtime(file_path))
    }


def update_existing_object(obj, rel_path, file_path, obj_info, import_managers, force=False):
    """
    Update an existing IDE object from a disk file.
    
    Args:
        obj: The CODESYS object to update
        rel_path: Relative path (for manager selection)
        file_path: Absolute path to the source file
        obj_info: Metadata dict for this object (may be modified in-place)
        import_managers: Manager dict from create_import_managers()
        force: If True, ignore content_hash match and always update
        
    Returns:
        True if the object was updated, False if skipped
    """
    obj_type = obj_info.get("type", "")
    manager = resolve_manager(import_managers, obj_type, rel_path)
    
    if force:
        # Override the stored hash so the manager always detects a change
        temp_info = obj_info.copy()
        temp_info["content_hash"] = "FORCE_SYNC"
        return manager.update(obj, file_path, temp_info)
    else:
        return manager.update(obj, file_path, obj_info)


def create_new_object(rel_path, file_path, import_managers, name_map, 
                      folder_cache, project, objects_meta):
    """
    Create a new IDE object from a disk file.
    
    Args:
        rel_path: Relative path of the file
        file_path: Absolute path to the source file
        import_managers: Manager dict from create_import_managers()
        name_map: Name cache from build_object_cache()
        folder_cache: Dict for caching folder resolutions (modified in-place)
        project: The CODESYS project object
        objects_meta: Metadata dict (updated on success)
        
    Returns:
        The created object, or None on failure
    """
    path_parts = rel_path.split("/")
    
    # 1. Ensure parent folder structure exists
    if len(path_parts) > 1:
        folder_path = "/".join(path_parts[:-1])
        if folder_path in folder_cache:
            container = folder_cache[folder_path]
        else:
            container = ensure_folder_path(folder_path, project)
            folder_cache[folder_path] = container
    else:
        container = project
        
    if not container:
        log_error("Could not find or create container for " + rel_path)
        return None
    
    # 2. Determine type and name
    base_name = os.path.splitext(path_parts[-1])[0]
    
    if rel_path.endswith(".xml"):
        # XML files don't need type detection — they'll go through native batch
        return None  # Handled separately by batch_import_native_xmls
    
    decl, impl = parse_st_file(file_path)
    content_check = decl if decl else impl
    if not content_check:
        return None
    
    type_guid = determine_object_type(content_check)
    
    # Handle nested objects (Action, Method, Property)
    name = base_name
    nested_types = [TYPE_GUIDS.get("action"), TYPE_GUIDS.get("method"), 
                    TYPE_GUIDS.get("property"), TYPE_GUIDS.get("property_accessor")]
    if "." in base_name and type_guid in nested_types:
        parts = base_name.rsplit(".", 1)
        parent_name = parts[0]
        name = parts[1]
        pou_parent = find_object_by_name(parent_name, name_map)
        if pou_parent:
            container = pou_parent
    
    # 3. Create via appropriate manager
    manager = resolve_manager(import_managers, type_guid, rel_path)
    res = manager.create(container, name, file_path, type_guid)
    
    if res:
        update_object_metadata(objects_meta, rel_path, res, file_path, import_managers)
        # Update name cache
        obj_name = res.get_name()
        if obj_name not in name_map:
            name_map[obj_name] = []
        name_map[obj_name].append(res)
        log_info("Created " + rel_path)
    else:
        log_error("Failed to create " + rel_path)
    
    return res


def batch_import_native_xmls(native_batches, import_managers, objects_meta, project):
    """
    Process batched native XML imports to reduce dialogs.
    
    Args:
        native_batches: dict { container_obj: [(rel_path, file_path, name, type_guid, is_new)] }
        import_managers: Manager dict
        objects_meta: Metadata dict (updated in-place)
        project: The CODESYS project object (fallback container)
        
    Returns:
        (updated_count, created_count, failed_count)
    """
    updated = 0
    created = 0
    failed = 0
    
    for container, items in native_batches.items():
        print("  Batch importing " + str(len(items)) + " native objects into " + safe_str(container))
        temp_xml = os.path.join(tempfile.gettempdir(), "cds_sync_batch.xml")
        file_paths = [item[1] for item in items]
        
        if merge_native_xmls(file_paths, temp_xml):
            try:
                if hasattr(container, "import_native"):
                    container.import_native(temp_xml)
                else:
                    project.import_native(temp_xml)
                
                # Resolve results and update metadata
                for rel_path, file_path, name, type_guid, is_new in items:
                    res = None
                    try:
                        for child in container.get_children():
                            if child.get_name().lower() == name.lower():
                                res = child
                                break
                    except:
                        pass
                    
                    if res:
                        if is_new:
                            created += 1
                        else:
                            updated += 1
                            print("  Updated (native batch): " + rel_path)
                        update_object_metadata(objects_meta, rel_path, res, file_path, import_managers)
                    else:
                        log_error("Batch import could not find " + name + " after import.")
                        failed += 1
                        
            except Exception as e:
                log_error("Batch import failed for " + safe_str(container) + ": " + safe_str(e))
                failed += len(items)
        else:
            log_error("Failed to merge XML for " + safe_str(container))
            failed += len(items)
        
        # Cleanup temp file
        if os.path.exists(temp_xml):
            try:
                os.remove(temp_xml)
            except:
                pass
    
    return updated, created, failed


def finalize_import(base_dir, metadata, project, projects_obj,
                    updated_count, created_count, deleted_count=0):
    """
    Save metadata and optionally save project + backup.
    Called after all import operations are complete.
    """
    if updated_count > 0 or created_count > 0 or deleted_count > 0:
        save_metadata(base_dir, metadata)
        
        should_save = get_project_prop("cds-sync-save-after-import", True)
        backup_binary = get_project_prop("cds-sync-backup-binary", False)
        must_save = should_save or backup_binary
        
        if must_save:
            try:
                print("  Saving project...")
                project.save()
                if backup_binary:
                    print("  Updating binary backup...")
                    backup_project_binary(base_dir, projects_obj)
            except Exception as e:
                print("  Warning: Could not save project: " + safe_str(e))
        else:
            print("  Skipping project save (user option).")

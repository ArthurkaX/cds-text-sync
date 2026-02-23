# -*- coding: utf-8 -*-
"""
codesys_compare_engine.py - Shared comparison and import engine

Single engine used by both Project_compare.py and Project_import.py.
Provides:
  - find_all_changes()       : compare IDE objects with disk files  
  - scan_new_disk_files()    : find files on disk not tracked in metadata
  - perform_import_items()   : import selected items from disk to IDE
  - create_import_managers() : create manager dict for import operations
  - update_existing_object() : update an existing IDE object from disk file  
  - create_new_object()      : create a new IDE object from disk file
  - batch_import_native_xmls() : batch-import native XML objects
  - update_object_metadata() : update metadata entry after import
  - finalize_import()        : save metadata and project after import
"""
import os
import codecs
import tempfile

from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES
from codesys_utils import (
    safe_str, calculate_hash, format_st_content, log_info, log_error,
    format_property_content, clean_filename, find_object_by_path,
    find_object_by_name, build_object_cache, MetadataLock, resolve_projects,
    parse_st_file, ensure_folder_path, determine_object_type,
    save_metadata, merge_native_xmls, get_project_prop, backup_project_binary
)
from codesys_managers import (
    get_object_path, get_container_prefix, get_parent_pou_name,
    export_object_content, collect_property_accessors, is_nvl, is_graphical_pou,
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    update_object_code
)

# Reverse mapping for friendly type names
TYPE_NAMES = {v: k for k, v in TYPE_GUIDS.items()}

# Files/dirs to skip when scanning disk
RESERVED_FILES = {
    "_metadata.json", "_config.json", "_metadata.csv", "BASE_DIR",
    "sync_debug.log", "compare.log", ".project", ".gitattributes",
    ".gitignore"
}


# ═══════════════════════════════════════════════════════════════════
#  COMPARISON ENGINE
# ═══════════════════════════════════════════════════════════════════

def find_all_changes(base_dir, projects_obj, metadata):
    """
    Compare IDE objects with disk files.  Full three-way comparison.
    
    Returns a dict:
        {
            "modified":         [{"name", "path", "type", "type_guid", "direction", "obj",
                                  "ide_content", "disk_content"}, ...],
            "new_in_ide":       [{"name", "path", "type", "type_guid", "obj"}, ...],
            "deleted_from_ide": [{"name", "path", "type", "type_guid"}, ...],
            "new_on_disk":      [{"name", "path", "file_path"}, ...],
            "unchanged_count":  int
        }
    """
    disk_objects = metadata.get("objects", {})

    # Build IDE caches
    guid_map, name_map = build_object_cache(projects_obj.primary)
    all_ide_objects = projects_obj.primary.get_children(recursive=True)

    modified = []
    new_in_ide = []
    deleted_from_ide = []
    unchanged_count = 0
    matched_disk_paths = set()

    # Collect property accessors
    property_accessors = collect_property_accessors(all_ide_objects)
    native_mgr = NativeManager()

    # ── Pass 1: Compare each IDE object with disk ──
    for obj in all_ide_objects:
        try:
            if not hasattr(obj, 'type') or not hasattr(obj, 'get_name') or not hasattr(obj, 'guid'):
                continue

            obj_type = safe_str(obj.type)
            obj_name = obj.get_name()
            obj_guid = safe_str(obj.guid)

            # Skip property accessors, folders, individual tasks
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

            # Gate: XML types not always exported
            if is_xml_object and effective_type in XML_TYPES:
                always_exported = effective_type in [
                    TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]
                ]
                if not always_exported and not metadata.get("export_xml", False) \
                   and rel_path not in disk_objects:
                    continue

            type_name = TYPE_NAMES.get(effective_type, effective_type[:8])

            # ── Object exists in both IDE and metadata ──
            if rel_path in disk_objects:
                matched_disk_paths.add(rel_path)
                disk_info = disk_objects[rel_path]
                meta_hash = disk_info.get("content_hash", "")

                if is_xml_object:
                    file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))

                    # Disk hash
                    disk_file_hash = ""
                    disk_content = ""
                    if os.path.exists(file_path):
                        disk_file_hash = native_mgr._hash_file(file_path)
                        try:
                            with codecs.open(file_path, "r", "utf-8") as df:
                                disk_content = df.read()
                        except:
                            pass

                    # IDE hash
                    ide_hash = ""
                    ide_content = ""
                    try:
                        tmp_path = os.path.join(tempfile.gettempdir(), "cds_comp_" + clean_name + ".xml")
                        projects_obj.primary.export_native([obj], tmp_path, recursive=True)
                        if os.path.exists(tmp_path):
                            ide_hash = native_mgr._hash_file(tmp_path)
                            with codecs.open(tmp_path, "r", "utf-8") as tf:
                                ide_content = tf.read()
                            os.remove(tmp_path)
                    except:
                        pass

                    # Three-way comparison
                    ide_changed = (ide_hash != "" and ide_hash != meta_hash)
                    disk_changed = (disk_file_hash != "" and disk_file_hash != meta_hash)

                    if ide_changed and disk_changed:
                        direction = "both"
                    elif ide_changed:
                        direction = "ide"
                    elif disk_changed:
                        direction = "disk"
                    else:
                        direction = None

                    if direction:
                        modified.append({
                            "name": obj_name, "path": rel_path, "type": type_name,
                            "type_guid": effective_type, "direction": direction,
                            "obj": obj, "ide_content": ide_content, "disk_content": disk_content
                        })
                    else:
                        unchanged_count += 1
                else:
                    # ── ST content comparison ──
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

                    # Read disk file
                    disk_file_hash = ""
                    disk_content = ""
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
                        direction = "both"
                    elif ide_changed:
                        direction = "ide"
                    elif disk_changed:
                        direction = "disk"
                    else:
                        direction = None

                    if direction:
                        modified.append({
                            "name": obj_name, "path": rel_path, "type": type_name,
                            "type_guid": effective_type, "direction": direction,
                            "obj": obj, "ide_content": ide_content, "disk_content": disk_content
                        })
                    else:
                        unchanged_count += 1
            else:
                # ── Object in IDE but not in metadata → new in IDE ──
                if is_xml_object:
                    try:
                        tmp_path = os.path.join(tempfile.gettempdir(), "cds_new_check_" + clean_name + ".xml")
                        projects_obj.primary.export_native([obj], tmp_path, recursive=True)
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                        else:
                            continue
                    except:
                        continue
                else:
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
                    "name": obj_name, "path": rel_path, "type": type_name,
                    "type_guid": effective_type, "obj": obj
                })

        except Exception as e:
            print("Error processing object: " + safe_str(e))
            continue

    # ── Pass 2: Objects in metadata but not matched in IDE ──
    for rel_path, disk_info in disk_objects.items():
        if disk_info.get("type") == TYPE_GUIDS["folder"]:
            continue
        if not rel_path.endswith(".st") and not rel_path.endswith(".xml"):
            continue
        if rel_path in matched_disk_paths:
            continue

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
            "name": obj_name, "path": rel_path, "type": type_name,
            "type_guid": obj_type_guid
        })

    # ── Pass 3: Scan disk for files not in metadata ──
    new_on_disk = scan_new_disk_files(base_dir, disk_objects)

    return {
        "modified": modified,
        "new_in_ide": new_in_ide,
        "deleted_from_ide": deleted_from_ide,
        "new_on_disk": new_on_disk,
        "unchanged_count": unchanged_count
    }


def scan_new_disk_files(base_dir, disk_objects):
    """
    Walk the export directory and find .st / .xml files that are
    NOT tracked in metadata.  These are files added externally
    (e.g. via git pull).
    
    Returns:
        list of {"name": str, "path": rel_path, "file_path": abs_path}
    """
    new_files = []
    known_paths = set(disk_objects.keys())

    for root, dirs, files in os.walk(base_dir):
        # Skip hidden dirs and special dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "project"]

        rel_root = os.path.relpath(root, base_dir)
        if rel_root == ".":
            rel_root = ""

        for f in files:
            if not (f.endswith(".st") or f.endswith(".xml")):
                continue
            if f in RESERVED_FILES or f.startswith("."):
                continue

            if rel_root:
                rel_path = rel_root.replace("\\", "/") + "/" + f
            else:
                rel_path = f

            if rel_path not in known_paths:
                abs_path = os.path.join(root, f)
                name = os.path.splitext(f)[0]
                new_files.append({
                    "name": name,
                    "path": rel_path,
                    "file_path": abs_path
                })

    return new_files


# ═══════════════════════════════════════════════════════════════════
#  IMPORT ENGINE
# ═══════════════════════════════════════════════════════════════════

def create_import_managers():
    """Create the standard manager dict used by import operations."""
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
    
    Returns:
        True if the object was updated, False if skipped
    """
    obj_type = obj_info.get("type", "")
    manager = resolve_manager(import_managers, obj_type, rel_path)
    
    if force:
        temp_info = obj_info.copy()
        temp_info["content_hash"] = "FORCE_SYNC"
        return manager.update(obj, file_path, temp_info)
    else:
        return manager.update(obj, file_path, obj_info)


def create_new_object(rel_path, file_path, import_managers, name_map, 
                      folder_cache, project, objects_meta):
    """
    Create a new IDE object from a disk file.
    
    Returns:
        The created object, or None on failure
    """
    path_parts = rel_path.split("/")
    
    # Ensure parent folder structure exists
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
    
    base_name = os.path.splitext(path_parts[-1])[0]
    
    if rel_path.endswith(".xml"):
        # XML files are handled by batch_import_native_xmls
        return None
    
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
    
    manager = resolve_manager(import_managers, type_guid, rel_path)
    res = manager.create(container, name, file_path, type_guid)
    
    if res:
        update_object_metadata(objects_meta, rel_path, res, file_path, import_managers)
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


# ═══════════════════════════════════════════════════════════════════
#  HIGH-LEVEL IMPORT ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════

def perform_import_items(primary_project, base_dir, to_sync, metadata, globals_ref=None):
    """
    Import selected items from disk to IDE.
    
    Handles both ST (textual) and XML (native) objects.
    XML objects are batched per container for a single import dialog.
    
    Args:
        primary_project: The CODESYS primary project object
        base_dir: Export/import directory path
        to_sync: list of item dicts (must have "path", "name", "type_guid"; optionally "obj")
        metadata: Full metadata dict
        globals_ref: globals() from calling script (for resolve_projects)
        
    Returns:
        (updated_count, created_count, failed_count)
    """
    if not to_sync:
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
                abs_path = item.get("file_path") or os.path.join(base_dir, rel_path.replace("/", os.sep))

                if not os.path.exists(abs_path):
                    continue

                # XML files → batch
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

                # ST files → find or create
                obj = item.get("obj")
                if not obj:
                    obj = find_object_by_path(rel_path, primary_project)

                if obj:
                    obj_info = objects_meta.get(rel_path, {})
                    if not obj_info.get("type"):
                        obj_info["type"] = item.get("type_guid", "")

                    if update_existing_object(obj, rel_path, abs_path, obj_info,
                                              import_managers, force=True):
                        update_object_metadata(objects_meta, rel_path, obj, abs_path, import_managers)
                        updated_count += 1
                        log_info("Updated " + item["name"])
                else:
                    res = create_new_object(
                        rel_path, abs_path, import_managers, name_map,
                        folder_cache, primary_project, objects_meta
                    )
                    if res:
                        created_count += 1
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
        projects_obj = resolve_projects(None, globals_ref or globals())
        finalize_import(base_dir, metadata, primary_project, projects_obj,
                        updated_count, created_count)

    return updated_count, created_count, failed_count

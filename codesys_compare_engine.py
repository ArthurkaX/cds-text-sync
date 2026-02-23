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
from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, RESERVED_FILES, TYPE_NAMES
from codesys_utils import (
    safe_str, calculate_hash, clean_filename, log_info, log_error, log_warning,
    resolve_projects, backup_project_binary, merge_native_xmls,
    parse_st_file, build_object_cache, find_object_by_path,
    ensure_folder_path, determine_object_type, find_object_by_name,
    format_st_content, format_property_content, get_project_prop
)
from codesys_managers import (
    NativeManager, FolderManager, PropertyManager, ConfigManager, POUManager,
    collect_property_accessors, classify_object, get_container_prefix,
    get_object_path, get_parent_pou_name, export_object_content
)


# ═══════════════════════════════════════════════════════════════════
#  COMPARISON ENGINE
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
#  COMPARISON ENGINE (2-WAY)
# ═══════════════════════════════════════════════════════════════════

def build_expected_path(obj, effective_type, is_xml):
    """Build the expected rel_path for an IDE object."""
    
    container = get_container_prefix(obj)
    path_parts = get_object_path(obj)
    obj_name = obj.get_name()
    clean_name = clean_filename(obj_name)

    if is_xml:
        file_name = clean_name + ".xml"
    else:
        obj_type = safe_str(obj.type)
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
        return "/".join(full_path_parts) + "/" + file_name
    return file_name

def get_ide_content(obj, is_xml, property_accessors, projects_obj):
    """Extract content from IDE object for comparison."""
    
    if is_xml:
        native_mgr = NativeManager()
        clean_name = clean_filename(obj.get_name())
        tmp_path = os.path.join(tempfile.gettempdir(), "cds_comp_" + clean_name + ".xml")
        try:
            # ConfigManager objects (Task Config, Alarm Config, Visu Manager) require recursive=True
            recursive = safe_str(obj.type) in [
                TYPE_GUIDS["task_config"], TYPE_GUIDS["alarm_config"], TYPE_GUIDS["visu_manager"]
            ]
            projects_obj.primary.export_native([obj], tmp_path, recursive=recursive)
            if os.path.exists(tmp_path):
                content = read_file(tmp_path)
                os.remove(tmp_path)
                return content
        except:
            pass
        return ""
    
    # ST content
    obj_guid = safe_str(obj.guid)
    obj_type = safe_str(obj.type)
    
    if obj_type == TYPE_GUIDS["property"] and obj_guid in property_accessors:
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

        return format_property_content(declaration, get_impl, set_impl)
    
    declaration, implementation = export_object_content(obj)
    return format_st_content(declaration, implementation)

def contents_are_equal(ide_content, disk_content, is_xml, rel_path="unknown"):
    """Compare two content strings, with XML-specific filtering."""
    log_info("=== Comparing %s ===" % rel_path)
    log_info("IDE content length: %d, Disk content length: %d" % (len(ide_content), len(disk_content)))
    
    if not ide_content or not disk_content:
        result = ide_content == disk_content
        log_info("Empty content check: %s (IDE empty: %s, Disk empty: %s)" % (result, not ide_content, not disk_content))
        return result
        
    if not is_xml:
        ide_hash = calculate_hash(ide_content)
        disk_hash = calculate_hash(disk_content)
        result = ide_hash == disk_hash
        log_info("Non-XML comparison: IDE hash=%s, Disk hash=%s, Equal=%s" % (ide_hash, disk_hash, result))
        return result
    
    # XML Comparison - use NativeManager's filtering logic
    native_mgr = NativeManager()
    
    # We need to write ide_content to a temp file because _hash_file reads from disk
    clean_name = "ide_temp_comp"
    tmp_path = os.path.join(tempfile.gettempdir(), clean_name + ".xml")
    tmp_path_disk = os.path.join(tempfile.gettempdir(), "disk_temp_comp" + ".xml")
    
    try:
        with codecs.open(tmp_path, "w", "utf-8") as f:
            f.write(ide_content)
        with codecs.open(tmp_path_disk, "w", "utf-8") as f:
            f.write(disk_content)
            
        ide_hash = native_mgr._hash_file(tmp_path)
        disk_hash = native_mgr._hash_file(tmp_path_disk)
        
        os.remove(tmp_path)
        os.remove(tmp_path_disk)
        
        are_equal = ide_hash == disk_hash
        if not are_equal:
            log_info("Content mismatch: IDE hash=%s, Disk hash=%s" % (ide_hash, disk_hash))
            
            # Log first few lines of each content for debugging
            ide_lines = ide_content.splitlines()[:5]
            disk_lines = disk_content.splitlines()[:5]
            
            log_info("=== First 5 lines comparison ===")
            for i, (ide_line, disk_line) in enumerate(zip(ide_lines, disk_lines), 1):
                if ide_line != disk_line:
                    log_info("Line %d DIFFERS:")
                    log_info("  IDE: %s" % ide_line[:100])
                    log_info("  Disk: %s" % disk_line[:100])
                else:
                    log_info("Line %d: %s" % (i, ide_line[:100]))
        else:
            log_info("Content match: IDE hash=%s, Disk hash=%s" % (ide_hash, disk_hash))
            
        return are_equal
    except Exception as e:
        log_info("Error during comparison: %s" % str(e))
        return False

def read_file(file_path):
    """Read file content as UTF-8."""
    if not os.path.exists(file_path):
        return ""
    try:
        with codecs.open(file_path, "r", "utf-8") as f:
            return f.read()
    except:
        return ""

def find_all_changes(base_dir, projects_obj, export_xml=False):
    """
    Direct two-way comparison: IDE objects ↔ Disk files.

    Returns:
        {
            "different":        [{"name", "path", "type", "type_guid", "obj",
                                  "ide_content", "disk_content"}, ...],
            "new_in_ide":       [{"name", "path", "type", "type_guid", "obj"}, ...],
            "new_on_disk":      [{"name", "path", "file_path"}, ...],
            "unchanged_count":  int
        }
    """
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    property_accessors = collect_property_accessors(all_ide_objects)

    ide_paths = {}  # rel_path → obj (to match disk files later)
    different = []
    new_in_ide = []
    unchanged_count = 0
    # Pass 1: For each IDE object, find & compare with disk file
    for obj in all_ide_objects:
        effective_type, is_xml, should_skip = classify_object(obj)
        if should_skip:
            continue

        # XML gate: skip non-always-exported XML types when export_xml is off
        if is_xml and effective_type in XML_TYPES:
            always_exported = effective_type in [
                TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]
            ]
            if not always_exported and not export_xml:
                continue

        rel_path = build_expected_path(obj, effective_type, is_xml)
        ide_paths[rel_path] = obj

        file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
        type_name = TYPE_NAMES.get(effective_type, effective_type[:8])

        if os.path.exists(file_path):
            # Compare content
            ide_content = get_ide_content(obj, is_xml, property_accessors, projects_obj)
            disk_content = read_file(file_path)

            if contents_are_equal(ide_content, disk_content, is_xml, rel_path):
                unchanged_count += 1
            else:
                different.append({
                    "name": obj.get_name(), "path": rel_path,
                    "type": type_name, "type_guid": effective_type,
                    "obj": obj, "ide_content": ide_content, "disk_content": disk_content
                })
        else:
            new_in_ide.append({
                "name": obj.get_name(), "path": rel_path,
                "type": type_name, "type_guid": effective_type, "obj": obj
            })

    # ── Pass 2: Walk disk, find files not matching any IDE object ──
    new_on_disk = scan_new_disk_files(base_dir, ide_paths)

    return {
        "different": different,
        "new_in_ide": new_in_ide,
        "new_on_disk": new_on_disk,
        "unchanged_count": unchanged_count
    }


def scan_new_disk_files(base_dir, ide_paths):
    """
    Walk the export directory and find .st / .xml files that are
    NOT matching any IDE object path.
    
    Returns:
        list of {"name": str, "path": rel_path, "file_path": abs_path}
    """
    new_files = []
    known_paths = set(ide_paths.keys())

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
        TYPE_GUIDS["alarm_config"]: ConfigManager(),
        TYPE_GUIDS["visu_manager"]: ConfigManager(),
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


# Removed update_object_metadata (metadata files no longer used)


def update_existing_object(obj, rel_path, file_path, import_managers):
    """Update an existing IDE object from a disk file."""
    # We no longer use obj_info/metadata hashes. Import always forces content update.
    # managers[type].update already checks for change before applying to IDE.
    manager = resolve_manager(import_managers, safe_str(obj.type), rel_path)
    return manager.update(obj, file_path, {})


def create_new_object(rel_path, file_path, import_managers, name_map, 
                      folder_cache, project):
    """Create a new IDE object from a disk file."""
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
    # A dotted base_name like "ST_PROGRAMM.ST_ACTION" means it's a child object.
    # We check both: (a) when type_guid indicates a child type, and
    #                 (b) when type_guid is None/unknown but filename has a dot.
    name = base_name
    nested_types = [TYPE_GUIDS.get("action"), TYPE_GUIDS.get("method"), 
                    TYPE_GUIDS.get("property"), TYPE_GUIDS.get("property_accessor")]
    is_nested = "." in base_name and (
        type_guid in nested_types or       # Known child type (method, property, etc.)
        not type_guid or                   # Unknown type (e.g. action with no keyword)
        type_guid == TYPE_GUIDS.get("pou") # Misdetected as POU
    )
    if is_nested:
        parts = base_name.rsplit(".", 1)
        parent_name = parts[0]
        child_name = parts[1]
        pou_parent = find_object_by_name(parent_name, name_map)
        if pou_parent:
            name = child_name
            container = pou_parent
            # If type_guid wasn't determined, infer from child name patterns
            if not type_guid or type_guid == TYPE_GUIDS.get("pou"):
                upper_child = child_name.upper()
                if upper_child in ("GET", "SET"):
                    type_guid = TYPE_GUIDS.get("property_accessor")
                else:
                    # Default to action for unknown nested children
                    type_guid = TYPE_GUIDS.get("action")
    
    manager = resolve_manager(import_managers, type_guid, rel_path)
    res = manager.create(container, name, file_path, type_guid)
    
    if res:
        obj_name = res.get_name()
        if obj_name not in name_map:
            name_map[obj_name] = []
        name_map[obj_name].append(res)
        log_info("Created " + rel_path)
    else:
        log_error("Failed to create " + rel_path)
    
    return res


def batch_import_native_xmls(native_batches, import_managers, project):
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


def finalize_import(project, projects_obj, base_dir, updated_count, created_count, deleted_count=0):
    """
    Optionally save project + backup.
    Called after all import operations are complete.
    """
    if updated_count > 0 or created_count > 0 or deleted_count > 0:
        
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

def perform_import_items(primary_project, base_dir, to_sync, globals_ref=None):
    """
    Import selected items from disk to IDE.
    
    Handles both ST (textual) and XML (native) objects.
    XML objects are batched per container for a single import dialog.
    
    Args:
        primary_project: The CODESYS primary project object
        base_dir: Export/import directory path
        to_sync: list of item dicts (must have "path", "name", "type_guid"; optionally "obj")
        globals_ref: globals() from calling script (for resolve_projects)
        
    Returns:
        (updated_count, created_count, failed_count)
    """
    if not to_sync:
        return 0, 0, 0

    import_managers = create_import_managers()
    guid_map, name_map = build_object_cache(primary_project)
    folder_cache = {}

    updated_count = 0
    created_count = 0
    failed_count = 0
    native_batches = {}

    # We no longer use MetadataLock as metadata files are removed
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
                else:
                    # New XML file: resolve correct container from path
                    # e.g. "CODESYS_HMI/HMI_Application/MFL_VISU/Screen2.xml"
                    #   → container = MFL_VISU folder object
                    path_parts = rel_path.replace("\\", "/").split("/")
                    if len(path_parts) > 1:
                        parent_path = "/".join(path_parts[:-1])
                        resolved = ensure_folder_path(parent_path, primary_project)
                        if resolved:
                            container = resolved

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
                if update_existing_object(obj, rel_path, abs_path, import_managers):
                    updated_count += 1
                    log_info("Updated " + item["name"])
            else:
                res = create_new_object(
                    rel_path, abs_path, import_managers, name_map,
                    folder_cache, primary_project
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
            native_batches, import_managers, primary_project
        )
        updated_count += u
        created_count += c
        failed_count += f

    # Save project
    projects_obj = resolve_projects(None, globals_ref or globals())
    finalize_import(primary_project, projects_obj, base_dir,
                    updated_count, created_count)

    return updated_count, created_count, failed_count

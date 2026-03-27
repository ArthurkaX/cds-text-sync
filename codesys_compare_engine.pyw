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
import time
from codesys_constants import TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, IMPLEMENTATION_TYPES, RESERVED_FILES, TYPE_NAMES
from codesys_utils import (
    safe_str, calculate_hash, clean_filename, log_info, log_error, log_warning,
    resolve_projects, backup_project_binary, merge_native_xmls,
    parse_st_file, build_object_cache, find_object_by_path,
    ensure_folder_path, determine_object_type, find_object_by_name,
    format_st_content, format_property_content, get_project_prop,
    load_sync_cache, save_sync_cache, normalize_path, get_quick_ide_hash
)
from codesys_managers import (
    NativeManager, FolderManager, PropertyManager, ConfigManager, POUManager,
    collect_property_accessors, classify_object, get_container_prefix,
    get_object_path, get_parent_pou_name, export_object_content,
    build_expected_path, update_object_code
)


# ═══════════════════════════════════════════════════════════════════
#  COMPARISON ENGINE
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
#  COMPARISON ENGINE (2-WAY)
# ═══════════════════════════════════════════════════════════════════

# Removed local build_expected_path, now imported from codesys_managers


def get_ide_content(obj, is_xml, property_accessors, projects_obj, can_have_impl=False):
    """Extract content from IDE object for comparison.
    
    Args:
        obj: CODESYS object
        is_xml: True if this is an XML object
        property_accessors: Dictionary of property accessor objects
        projects_obj: CODESYS projects object
        can_have_impl: True if object type can have implementation even if empty
    """
    
    if is_xml:
        native_mgr = NativeManager()
        clean_name = clean_filename(obj.get_name())
        tmp_path = os.path.join(tempfile.gettempdir(), "cds_comp_" + clean_name + ".xml")
        try:
            # ConfigManager objects require recursive=True to include all children
            monolithic_types = [
                TYPE_GUIDS["task_config"], TYPE_GUIDS["alarm_config"], 
                TYPE_GUIDS["visu_manager"], TYPE_GUIDS["softmotion_pool"]
            ]
            obj_type = safe_str(obj.type)
            recursive = obj_type in monolithic_types
            
            # Special logic for devices: only recursive if not a project container
            if obj_type == TYPE_GUIDS["device"]:
                from codesys_utils import is_container_device
                recursive = not is_container_device(obj)
                
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
            get_impl = format_st_content(get_decl, get_impl_raw, False)

        set_impl = None
        if prop_data['set']:
            set_decl, set_impl_raw = export_object_content(prop_data['set'])
            set_impl = format_st_content(set_decl, set_impl_raw, False)

        return format_property_content(declaration, get_impl, set_impl)
    
    declaration, implementation = export_object_content(obj)
    return format_st_content(declaration, implementation, can_have_impl)

def contents_are_equal(ide_content, disk_content, is_xml, rel_path="unknown"):
    """Compare two content strings, with XML-specific filtering."""
    if not ide_content or not disk_content:
        return ide_content == disk_content
        
    if not is_xml:
        ide_hash = calculate_hash(ide_content)
        disk_hash = calculate_hash(disk_content)
        are_equal = ide_hash == disk_hash
        if not are_equal:
            log_info("Content mismatch for %s: IDE hash=%s, Disk hash=%s" % (rel_path, ide_hash, disk_hash))
        return are_equal
    
    # XML Comparison - use NativeManager's filtering logic
    native_mgr = NativeManager()
    
    # We need to write content to temp files because _hash_file reads from disk
    tmp_path_ide = os.path.join(tempfile.gettempdir(), "cds_comp_ide.xml")
    tmp_path_disk = os.path.join(tempfile.gettempdir(), "cds_comp_disk.xml")
    
    try:
        with codecs.open(tmp_path_ide, "w", "utf-8") as f:
            f.write(ide_content)
        with codecs.open(tmp_path_disk, "w", "utf-8") as f:
            f.write(disk_content)
            
        ide_hash = native_mgr._hash_file(tmp_path_ide)
        disk_hash = native_mgr._hash_file(tmp_path_disk)
        
        if os.path.exists(tmp_path_ide): os.remove(tmp_path_ide)
        if os.path.exists(tmp_path_disk): os.remove(tmp_path_disk)
        
        are_equal = ide_hash == disk_hash
        if not are_equal:
            log_info("Content match: IDE hash=%s, Disk hash=%s" % (ide_hash, disk_hash))
            log_info("Content mismatch for %s (XML)" % rel_path)
        return are_equal
    except Exception as e:
        log_warning("Error comparing XML contents for %s: %s" % (rel_path, str(e)))
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
    Direct two-way comparison with Merkle Tree optimization.
    
    1. Pass 1: Quick IDE scan (.text only) and folder hash building.
    2. Pass 2: Comparison using folder hashes to skip unchanged branches.
    """
    total_start = time.time()
    all_ide_objects = projects_obj.primary.get_children(recursive=True)
    
    # Load cache
    cache_data = load_sync_cache(base_dir)
    cached_objects = cache_data["objects"]
    cached_folders = cache_data["folders"]
    cached_types = cache_data.get("types", {})
    
    different = []
    new_in_ide = []
    unchanged_count = 0
    cache_hits = 0
    
    ide_paths = {}    # rel_path -> obj
    ide_hashes = {}   # norm_path -> ide_hash
    ide_metadata = {} # norm_path -> (eff_type, is_xml)
    current_types = {} # guid -> (eff_type, is_xml, rel_path)
    property_accessors = {} # (parent_guid, name) -> obj
    
    # ── Pass 1: Quick Batch Scan (IDE only) ──
    print("  Pass 1: Batch hashing IDE objects...")
    p1_start = time.time()
    path_cache_hits = 0
    for obj in all_ide_objects:
        obj_guid = safe_str(obj.guid)
        
        # Check type cache first to avoid classify_object AND path building
        # Cache stores (eff_type, is_xml, cached_rel_path)
        if obj_guid in cached_types:
            type_info = cached_types[obj_guid]
            eff_type, is_xml = type_info[0], type_info[1]
            rel_path = type_info[2] if len(type_info) > 2 else None
            should_skip = False if rel_path else True
            if rel_path:
                path_cache_hits += 1
        else:
            eff_type, is_xml, should_skip = classify_object(obj)
            if not should_skip:
                rel_path = build_expected_path(obj, eff_type, is_xml)
            else:
                rel_path = None
            
        if should_skip or not rel_path: 
            # Still check for property accessors even if folder/object is skipped
            # Actually, properties themselves are not skipped.
            continue
        
        # Optimization: Collect property accessors during this same loop
        if eff_type == TYPE_GUIDS["property"]:
            try:
                if obj_guid not in property_accessors:
                    property_accessors[obj_guid] = {'get': None, 'set': None}
                
                for child in obj.get_children():
                    child_name = child.get_name().upper()
                    if child_name == "GET":
                        property_accessors[obj_guid]['get'] = child
                    elif child_name == "SET":
                        property_accessors[obj_guid]['set'] = child
            except:
                pass

        # Update type cache with path
        current_types[obj_guid] = (eff_type, is_xml, rel_path)

        norm_path = normalize_path(rel_path)
        ide_paths[rel_path] = obj
        ide_metadata[norm_path] = (eff_type, is_xml)
        
        # Quick hash for ST
        q_hash = get_quick_ide_hash(obj, is_xml)
        
        # For XML objects: use cached ide_hash to allow Merkle skip for mixed folders
        if not q_hash and is_xml:
            cached_entry = cached_objects.get(norm_path)
            if cached_entry:
                q_hash = cached_entry.get("ide_hash")
                
        ide_hashes[norm_path] = q_hash

    # Build folder hashes (Merkle Tree)
    from codesys_utils import build_folder_hashes
    ide_folder_hashes = build_folder_hashes(ide_hashes)
    log_info("  Pass 1 complete ({} objects, {} path cache hits) in {:.2f}s".format(
        len(ide_hashes), path_cache_hits, time.time() - p1_start))

    # ── Pass 2: Comparison ──
    print("  Pass 2: Comparing with disk...")
    p2_start = time.time()
    new_cache_objects = {}
    
    for rel_path, obj in ide_paths.items():
        norm_path = normalize_path(rel_path)
        eff_type, is_xml = ide_metadata[norm_path]
        file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
        type_name = TYPE_NAMES.get(eff_type, eff_type[:8])
        
        if os.path.exists(file_path):
            # ── Fast path 1: Folder-level check ──
            # If parent folder hash matches, IDE hasn't changed.
            # We only need to check if disk file changed (mtime).
            parent_folder = "/".join(norm_path.split("/")[:-1])
            folder_match = False
            if parent_folder and parent_folder in ide_folder_hashes:
                if ide_folder_hashes[parent_folder] == cached_folders.get(parent_folder):
                    folder_match = True
            
            # Disk check
            mtime = os.path.getmtime(file_path)
            size = os.path.getsize(file_path)
            cached_entry = cached_objects.get(norm_path)
            
            disk_unchanged = cached_entry and \
                             cached_entry.get("disk_mtime") == mtime and \
                             cached_entry.get("disk_size") == size
            
            # ── CACHE HIT ──
            if folder_match and disk_unchanged:
                unchanged_count += 1
                cache_hits += 1
                new_cache_objects[norm_path] = cached_entry
                continue
                
            # ── Slow path: Full Comparison ──
            can_have_impl = eff_type in IMPLEMENTATION_TYPES
            ide_content = get_ide_content(obj, is_xml, property_accessors, projects_obj, can_have_impl)
            disk_content = read_file(file_path)

            if contents_are_equal(ide_content, disk_content, is_xml, rel_path):
                unchanged_count += 1
                # Update cache
                q_hash = ide_hashes[norm_path] or calculate_hash(ide_content)
                new_cache_objects[norm_path] = {
                    "ide_hash": q_hash,
                    "disk_hash": calculate_hash(disk_content),
                    "disk_mtime": mtime,
                    "disk_size": size
                }
            else:
                different.append({
                    "name": obj.get_name(), "path": rel_path,
                    "type": type_name, "type_guid": eff_type,
                    "obj": obj, "ide_content": ide_content, "disk_content": disk_content
                })
        else:
            new_in_ide.append({
                "name": obj.get_name(), "path": rel_path,
                "type": type_name, "type_guid": eff_type, "obj": obj,
                "is_orphan": True
            })

    # Finalize cache with newly built folder hashes and types
    save_sync_cache(base_dir, new_cache_objects, ide_folder_hashes, current_types)
    
    p2_elapsed = time.time() - p2_start
    total_elapsed = time.time() - total_start
    log_info("  Pass 2 complete in {:.2f}s".format(p2_elapsed))
    log_info("  Sync cache updated: %d hits, %d entries total" % (cache_hits, len(new_cache_objects)))
    print("  Compare engine finished in {:.2f}s".format(total_elapsed))

    # Pass 3: Disk Scan
    new_on_disk = scan_new_disk_files(base_dir, ide_paths)

    return {
        "different": different,
        "new_in_ide": new_in_ide,
        "new_on_disk": new_on_disk,
        "unchanged_count": unchanged_count
    }

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
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

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
                if f.endswith(".xml") and "." in name:
                    name_part, doc_type = name.rsplit(".", 1)
                    from codesys_constants import TYPE_NAMES
                    if doc_type in TYPE_NAMES.values() or doc_type == "pou_xml":
                        name = name_part
                        
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
        TYPE_GUIDS["device"]: ConfigManager(),
        TYPE_GUIDS["softmotion_pool"]: ConfigManager(),
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
        log_info("Looking for parent POU: " + parent_name + " for child: " + child_name)
        log_info("Name map has " + str(len(name_map)) + " entries")
        pou_parent = find_object_by_name(parent_name, name_map)
        if pou_parent:
            log_info("Found parent POU by name: " + safe_str(pou_parent))
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
        else:
            # Try to find parent by path as fallback
            parent_path = "/".join(path_parts[:-1])
            parent_path_with_name = parent_path + "/" + parent_name
            log_warning("Parent '" + parent_name + "' not found by name, trying path: " + parent_path_with_name)
            pou_parent = find_object_by_path(parent_path_with_name, project)
            if pou_parent:
                log_info("Found parent POU by path: " + safe_str(pou_parent))
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
            else:
                log_warning("Could not find parent POU '" + parent_name + "' by name or path. Will use full name: " + name)
    
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


def save_pou_children(pou_obj):
    """
    Save child objects (methods, actions, properties) of a POU before XML import.
    
    Returns list of child info dicts:
        [{'name': str, 'type_guid': str, 'declaration': str, 'implementation': str}, ...]
    """
    children_info = []
    
    child_types = [
        TYPE_GUIDS.get("action"),
        TYPE_GUIDS.get("method"),
        TYPE_GUIDS.get("property")
    ]
    
    try:
        for child in pou_obj.get_children():
            try:
                child_type = safe_str(child.type)
                if child_type in child_types:
                    decl, impl = export_object_content(child)
                    children_info.append({
                        'name': child.get_name(),
                        'type_guid': child_type,
                        'declaration': decl,
                        'implementation': impl
                    })
            except Exception as e:
                log_warning("Could not save child " + safe_str(child) + ": " + safe_str(e))
    except Exception as e:
        log_warning("Could not get children of " + safe_str(pou_obj) + ": " + safe_str(e))
    
    return children_info


def restore_pou_children(pou_obj, saved_children, import_managers, project):
    """
    Restore child objects (methods, actions, properties) after XML import.
    
    Updates existing children or creates new ones.
    """
    if not saved_children:
        return
    
    try:
        existing_children = {}
        for child in pou_obj.get_children():
            existing_children[child.get_name().lower()] = child
    except Exception as e:
        log_warning("Could not get children of POU " + safe_str(pou_obj) + ": " + safe_str(e))
        return
    
    for child_info in saved_children:
        try:
            child_name = child_info['name']
            child_type = child_info['type_guid']
            decl = child_info['declaration']
            impl = child_info['implementation']
            
            existing_child = existing_children.get(child_name.lower())
            
            if existing_child:
                log_info("Restoring child " + child_name + " of " + safe_str(pou_obj))
                if update_object_code(existing_child, decl, impl):
                    log_info("  Successfully updated " + child_name)
            else:
                log_info("Creating child " + child_name + " of " + safe_str(pou_obj))
                try:
                    new_child = pou_obj.create_object(
                        name=child_name,
                        type_guid=child_type
                    )
                    if new_child:
                        if update_object_code(new_child, decl, impl):
                            log_info("  Successfully created " + child_name)
                        else:
                            log_warning("  Could not update code for new child " + child_name)
                    else:
                        log_warning("  Could not create child " + child_name)
                except Exception as e:
                    log_warning("  Failed to create child " + child_name + ": " + safe_str(e))
        except Exception as e:
            log_warning("Failed to restore child: " + safe_str(e))


def batch_import_native_xmls_with_children(native_batches, import_managers, project, pou_children_info=None):
    """
    Process batched native XML imports to reduce dialogs.
    Restores POU children after XML import to prevent deletion.
    
    Args:
        native_batches: dict of {container: [(rel_path, abs_path, name, type_guid, is_new), ...]}
        import_managers: dict of managers
        project: CODESYS project
        pou_children_info: dict of {pou_name_lower: saved_children} to restore after import
    
    Returns:
        (updated_count, created_count, failed_count)
    """
    if pou_children_info is None:
        pou_children_info = {}
    
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
                
                # Restore POU children after XML import
                # Find POUs by name in the container
                for rel_path, file_path, name, type_guid, is_new in items:
                    pou_name_lower = name.lower()
                    if pou_name_lower in pou_children_info:
                        children = pou_children_info[pou_name_lower]
                        # Find the POU object in the container
                        pou_obj = None
                        try:
                            for child in container.get_children():
                                if child.get_name().lower() == pou_name_lower:
                                    pou_obj = child
                                    break
                        except Exception as e:
                            log_warning("Could not find POU " + name + " in container: " + safe_str(e))
                        
                        if pou_obj:
                            try:
                                restore_pou_children(pou_obj, children, import_managers, project)
                            except Exception as e:
                                log_warning("Could not restore children for POU " + name + ": " + safe_str(e))
                
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
                # Save POU children before XML import to prevent them from being deleted
                pou_children_to_restore = {}
                for rel_path, file_path, name, type_guid, is_new in items:
                    if type_guid == TYPE_GUIDS.get("pou") and not is_new:
                        try:
                            for child in container.get_children():
                                if child.get_name().lower() == name.lower():
                                    children = save_pou_children(child)
                                    if children:
                                        pou_children_to_restore[child] = children
                                    break
                        except Exception as e:
                            log_warning("Could not save children for POU " + name + ": " + safe_str(e))
                
                if hasattr(container, "import_native"):
                    container.import_native(temp_xml)
                else:
                    project.import_native(temp_xml)
                
                # Restore POU children after XML import
                for pou_obj, children in pou_children_to_restore.items():
                    try:
                        restore_pou_children(pou_obj, children, import_managers, project)
                    except Exception as e:
                        log_warning("Could not restore children for POU " + safe_str(pou_obj) + ": " + safe_str(e))
                
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
    Avoids double-save if binary backup is enabled (which already saves).
    """
    if updated_count > 0 or created_count > 0 or deleted_count > 0:
        should_save = get_project_prop("cds-sync-save-after-import", True)
        backup_binary = get_project_prop("cds-sync-backup-binary", False)

        if backup_binary:
            # backup_project_binary already calls project.save()
            print("  Updating binary backup and saving...")
            backup_project_binary(base_dir, projects_obj)
        elif should_save:
            try:
                print("  Saving project...")
                project.save()
            except Exception as e:
                print("  Warning: Could not save project: " + safe_str(e))
        else:
            print("  Skipping project save (user option).")


# ═══════════════════════════════════════════════════════════════════
#  HIGH-LEVEL IMPORT ORCHESTRATOR
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
        (updated_count, created_count, failed_count, deleted_count)
    """
    import_managers = create_import_managers()
    folder_cache = {}
    name_map = {}
    
    updated_count = 0
    created_count = 0
    deleted_count = 0
    failed_count = 0
    
    native_batches = {}
    st_files_to_import = []
    pou_children_info = {}
    
    # ═══════════════════════════════════════════════════════════════════
    #  PASS 1: Collect XML batches and ST files, save POU children
    # ═══════════════════════════════════════════════════════════════════
    for item in to_sync:
        try:
            # Handle Deletions (Orphans)
            if item.get("is_orphan"):
                obj = item.get("obj")
                if obj:
                    try:
                        obj.remove()
                        deleted_count += 1
                    except Exception as e:
                        log_error("Failed to delete " + item["name"] + ": " + safe_str(e))
                        failed_count += 1
                    continue

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

            # ST files → collect for later import
            st_files_to_import.append(item)

        except Exception as e:
            log_error("Failed to process " + item.get("path", "unknown") + ": " + safe_str(e))
            failed_count += 1

    # ═══════════════════════════════════════════════════════════════════
    #  PASS 2: Save POU children from existing POUs before XML import
    # ═══════════════════════════════════════════════════════════════════
    for container, items in native_batches.items():
        for rel_path, abs_path, name, type_guid, is_new in items:
            if type_guid == TYPE_GUIDS.get("pou") and not is_new:
                try:
                    for child in container.get_children():
                        if child.get_name().lower() == name.lower():
                            children = save_pou_children(child)
                            if children:
                                # Store children by POU name (not object) to find after import
                                pou_children_info[name.lower()] = children
                            break
                except Exception as e:
                    log_warning("Could not save children for POU " + name + ": " + safe_str(e))

    # ═══════════════════════════════════════════════════════════════════
    #  PASS 3: Process batched XML imports (restores children)
    # ═══════════════════════════════════════════════════════════════════
    if native_batches:
        u, c, f = batch_import_native_xmls_with_children(
            native_batches, import_managers, primary_project, pou_children_info
        )
        updated_count += u
        created_count += c
        failed_count += f
        
        # Update name_map with newly created POUs from XML import
        for container, items in native_batches.items():
            for rel_path, abs_path, name, type_guid, is_new in items:
                if is_new and type_guid == TYPE_GUIDS.get("pou"):
                    try:
                        for child in container.get_children():
                            if child.get_name().lower() == name.lower():
                                obj_name = child.get_name()
                                if obj_name not in name_map:
                                    name_map[obj_name] = []
                                if child not in name_map[obj_name]:
                                    name_map[obj_name].append(child)
                                log_info("Added new POU to name_map: " + obj_name)
                                break
                    except Exception as e:
                        log_warning("Could not update name_map for new POU " + name + ": " + safe_str(e))

    # ═══════════════════════════════════════════════════════════════════
    #  PASS 4: Import ST files (after POUs exist)
    # ═══════════════════════════════════════════════════════════════════
    
    for item in st_files_to_import:
        try:
            rel_path = item["path"]
            abs_path = item.get("file_path") or os.path.join(base_dir, rel_path.replace("/", os.sep))
            
            if not os.path.exists(abs_path):
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
            log_error("Failed to import ST " + item.get("path", "unknown") + ": " + safe_str(e))
            failed_count += 1

    # Save project
    projects_obj = resolve_projects(None, globals_ref or globals())
    finalize_import(primary_project, projects_obj, base_dir,
                    updated_count, created_count, deleted_count)

    return updated_count, created_count, failed_count, deleted_count

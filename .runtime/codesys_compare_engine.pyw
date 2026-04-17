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
  - batch_import_native_xmls_with_children() : batch-import native XML objects with child restore
  - update_object_metadata() : update metadata entry after import
  - finalize_import()        : save metadata and project after import
"""
import os
import codecs
import tempfile
import time
import sys

try:
    import importlib.util
    _HAS_IMPORTLIB_UTIL = True
except ImportError:
    _HAS_IMPORTLIB_UTIL = False

try:
    import imp
    _HAS_IMP = True
except ImportError:
    _HAS_IMP = False


def _load_sibling_module(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".pyw")
    if _HAS_IMPORTLIB_UTIL:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    if _HAS_IMP:
        module = imp.load_source(name, path)
        sys.modules[name] = module
        return module
    raise ImportError(name + ".pyw not found.")
from codesys_constants import RESERVED_FILES
try:
    from codesys_type_profiles import PROJECT_PROPERTY_KEY
except ImportError:
    PROJECT_PROPERTY_KEY = _load_sibling_module("codesys_type_profiles").PROJECT_PROPERTY_KEY
try:
    from codesys_type_system import (
        resolve_runtime_object, semantic_kind_to_guid, SEMANTIC_TYPE_NAMES,
        can_have_implementation_kind, is_xml_kind
    )
except ImportError:
    _type_system = _load_sibling_module("codesys_type_system")
    resolve_runtime_object = _type_system.resolve_runtime_object
    semantic_kind_to_guid = _type_system.semantic_kind_to_guid
    SEMANTIC_TYPE_NAMES = _type_system.SEMANTIC_TYPE_NAMES
    can_have_implementation_kind = _type_system.can_have_implementation_kind
    is_xml_kind = _type_system.is_xml_kind
from codesys_utils import (
    safe_str, calculate_hash, clean_filename, log_info, log_error, log_warning,
    resolve_projects, backup_project_binary, merge_native_xmls,
    parse_st_file, build_object_cache, find_object_by_path,
    ensure_folder_path, determine_object_type, find_object_by_name,
    format_st_content, format_property_content, get_project_prop,
    load_sync_cache, save_sync_cache, normalize_path, get_quick_ide_hash,
    parse_sync_pragmas, read_ide_attrs, normalize_sync_attrs,
    build_state_hash, render_sync_pragmas
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


def _new_temp_xml_path(prefix):
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".xml")
    os.close(fd)
    try:
        os.remove(path)
    except:
        pass
    return path


def get_ide_content(obj, is_xml, property_accessors, projects_obj, can_have_impl=False):
    """Extract content and attributes from IDE object for comparison.
    
    Returns:
        (ide_content, ide_attrs) where ide_attrs is a dict of non-default
        attributes, or empty dict for XML objects or on error.
    """
    ide_attrs = read_ide_attrs(obj)
    obj_name = safe_str(obj.get_name()) if obj else "<unknown>"
    obj_guid = safe_str(getattr(obj, "guid", None))
    
    if is_xml:
        native_mgr = NativeManager()
        tmp_path = _new_temp_xml_path("cds_comp_native_")
        try:
            # ConfigManager objects require recursive=True to include all children
            resolution = resolve_runtime_object(obj, get_project_prop(PROJECT_PROPERTY_KEY))
            obj_kind = resolution.get("semantic_kind")
            monolithic_types = ["task_config", "alarm_config", "visu_manager", "softmotion_pool"]
            recursive = obj_kind in monolithic_types
            
            # Special logic for devices: only recursive if not a project container
            if obj_kind == "device":
                from codesys_utils import is_container_device
                recursive = not is_container_device(obj)

            log_info("COMPARE XML export start: %s (%s), recursive=%s -> %s" % (
                obj_name, obj_guid, recursive, tmp_path))
            projects_obj.primary.export_native([obj], tmp_path, recursive=recursive)
            log_info("COMPARE XML export done: %s (%s)" % (obj_name, obj_guid))
            if os.path.exists(tmp_path):
                content = read_file(tmp_path)
                os.remove(tmp_path)
                return content, {}
        except Exception as e:
            log_warning("COMPARE XML export failed: %s (%s): %s" % (
                obj_name, obj_guid, safe_str(e)))
        return "", {}
    
    # ST content
    obj_guid = safe_str(obj.guid)
    obj_type = safe_str(obj.type)
    obj_resolution = resolve_runtime_object(obj, get_project_prop(PROJECT_PROPERTY_KEY))

    if obj_resolution.get("semantic_kind") == "property" and obj_guid in property_accessors:
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

        return format_property_content(declaration, get_impl, set_impl), ide_attrs
    
    declaration, implementation = export_object_content(obj)
    return format_st_content(declaration, implementation, can_have_impl), ide_attrs

def contents_are_equal(ide_content, disk_content, is_xml, rel_path="unknown", ide_attrs=None, disk_attrs=None):
    """Compare two content strings, with XML-specific filtering.
    
    For ST files, also compares sync pragma attributes if provided.
    Returns True only if both code and attributes match.
    """
    if not ide_content or not disk_content:
        return ide_content == disk_content
        
    if not is_xml:
        # For ST files: strip pragmas from disk content for code comparison
        _, clean_disk_st = parse_sync_pragmas(disk_content)
        ide_hash = calculate_hash(ide_content)
        disk_hash = calculate_hash(clean_disk_st)
        are_equal = ide_hash == disk_hash
        if not are_equal:
            log_info("Content mismatch for %s: IDE hash=%s, Disk hash=%s" % (rel_path, ide_hash, disk_hash))
            return False
        
        # Code matches — now compare attributes
        if ide_attrs is not None and disk_attrs is not None:
            if normalize_sync_attrs(ide_attrs) != normalize_sync_attrs(disk_attrs):
                attr_diff = []
                from codesys_constants import ATTR_ORDER
                for k in ATTR_ORDER:
                    if ide_attrs.get(k) != disk_attrs.get(k):
                        attr_diff.append("%s: IDE=%s Disk=%s" % (k, ide_attrs.get(k), disk_attrs.get(k)))
                log_info("Attribute mismatch for %s: %s" % (rel_path, ", ".join(attr_diff)))
                return False
        
        return are_equal
    
    # XML Comparison - use NativeManager's filtering logic
    native_mgr = NativeManager()
    
    # We need to write content to temp files because _hash_file reads from disk
    tmp_path_ide = _new_temp_xml_path("cds_comp_ide_")
    tmp_path_disk = _new_temp_xml_path("cds_comp_disk_")
    
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


def _apply_nvl_path_hint(rel_path, resolution, base_dir):
    if not rel_path or not isinstance(resolution, dict):
        return rel_path, resolution

    semantic_kind = resolution.get("semantic_kind")
    if semantic_kind not in ("gvl", "nvl_sender"):
        return rel_path, resolution

    hinted_path = rel_path
    if rel_path.endswith(".gvl.xml"):
        candidate = rel_path[:-len(".gvl.xml")] + ".nvl_sender.xml"
        candidate_full = os.path.join(base_dir, candidate.replace("/", os.sep))
        if os.path.exists(candidate_full):
            hinted_path = candidate
    elif rel_path.endswith(".nvl_sender.xml"):
        hinted_path = rel_path

    if hinted_path.endswith(".nvl_sender.xml"):
        profile_name = resolution.get("profile_name")
        resolution = dict(resolution)
        resolution["semantic_kind"] = "nvl_sender"
        resolution["sync_profile"] = "native_xml"
        resolution["is_xml"] = True
        resolution["manager_key"] = "nvl_sender"
        resolution["canonical_guid"] = semantic_kind_to_guid("nvl_sender", profile_name) or resolution.get("canonical_guid")
        resolution["effective_type"] = resolution.get("canonical_guid") or resolution.get("effective_type")
        resolution["type_guid"] = resolution.get("effective_type")
        evidence = list(resolution.get("evidence") or [])
        if "path_hint=nvl_sender" not in evidence:
            evidence.append("path_hint=nvl_sender")
        resolution["evidence"] = evidence

    return hinted_path, resolution

def find_all_changes(base_dir, projects_obj, export_xml=False, verbose=False):
    """
    Direct two-way comparison with Merkle Tree optimization.
    
    1. Pass 1: Quick IDE scan (.text only) and folder hash building.
    2. Pass 2: Comparison using folder hashes to skip unchanged branches.
    3. Pass 3: Disk scan for new files.
    4. Pass 4: Detect moved/renamed files by cross-referencing new_in_ide vs new_on_disk.
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
    path_invalidations = 0
    
    ide_paths = {}    # rel_path -> obj
    ide_hashes = {}   # norm_path -> ide_hash
    ide_metadata = {} # norm_path -> (eff_type, is_xml)
    ide_resolutions = {} # norm_path -> resolution dict
    ide_type_names = {}   # norm_path -> semantic/type label
    current_types = {} # guid -> (eff_type, is_xml, rel_path)
    property_accessors = {} # (parent_guid, name) -> obj
    
    # ── Pass 1: Quick Batch Scan (IDE only) ──
    if verbose:
        print("  Pass 1: Batch hashing IDE objects...")
    p1_start = time.time()
    path_cache_hits = 0
    for obj in all_ide_objects:
        obj_guid = safe_str(obj.guid)
        resolution = classify_object(obj)
        semantic_kind = resolution.get("semantic_kind")
        type_name = semantic_kind or safe_str(obj.type)[:8]
        
        # Check type cache first to avoid classify_object AND path building
        # Cache stores (eff_type, is_xml, cached_rel_path)
        if obj_guid in cached_types:
            type_info = cached_types[obj_guid]
            eff_type, is_xml = type_info[0], type_info[1]
            cached_rel_path = type_info[2] if len(type_info) > 2 else None
            should_skip = False if cached_rel_path else True
            
            if cached_rel_path:
                cached_rel_path, resolution = _apply_nvl_path_hint(cached_rel_path, resolution, base_dir)
                # Validate cached path: rebuild the real path from the live IDE tree.
                # If the object was moved/renamed in IDE, the cached path is stale.
                fresh_path = build_expected_path(obj, resolution)
                if fresh_path and fresh_path != cached_rel_path:
                    cached_nvl = cached_rel_path.endswith(".nvl_sender.xml")
                    fresh_gvl = fresh_path.endswith(".gvl.xml")
                    if cached_nvl and fresh_gvl and resolution.get("semantic_kind") == "gvl":
                        rel_path = cached_rel_path
                        path_cache_hits += 1
                        log_info("Keeping cached NVL path for GUID %s: '%s' (fresh path '%s' ignored)" % (
                            obj_guid, cached_rel_path, fresh_path
                        ))
                    else:
                        # Path changed in IDE — invalidate cached path
                        rel_path = fresh_path
                        path_invalidations += 1
                        log_info("Path invalidated for GUID %s: '%s' -> '%s'" % (obj_guid, cached_rel_path, fresh_path))
                else:
                    rel_path = cached_rel_path
                    path_cache_hits += 1
        else:
            eff_type = resolution.get("manager_key") or semantic_kind or resolution.get("canonical_guid") or safe_str(obj.type)
            is_xml = bool(resolution.get("is_xml"))
            should_skip = bool(resolution.get("should_skip"))
            if not should_skip:
                rel_path = build_expected_path(obj, resolution)
                rel_path, resolution = _apply_nvl_path_hint(rel_path, resolution, base_dir)
            else:
                rel_path = None
            
        if should_skip or not rel_path: 
            continue

        semantic_kind = resolution.get("semantic_kind")
        type_name = semantic_kind or safe_str(obj.type)[:8]
        eff_type = semantic_kind or eff_type
        
        # Optimization: Collect property accessors during this same loop
        if semantic_kind == "property":
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
        ide_resolutions[norm_path] = resolution
        ide_type_names[norm_path] = type_name
        
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
    if verbose:
        print("  Pass 1 complete ({} objects, {} path cache hits, {} invalidated) in {:.2f}s".format(
            len(ide_hashes), path_cache_hits, path_invalidations, time.time() - p1_start))

    # ── Pass 2: Comparison ──
    if verbose:
        print("  Pass 2: Comparing with disk...")
    p2_start = time.time()
    new_cache_objects = {}
    
    for rel_path, obj in ide_paths.items():
        norm_path = normalize_path(rel_path)
        eff_type, is_xml = ide_metadata[norm_path]
        resolution = ide_resolutions.get(norm_path, {})
        type_name = ide_type_names.get(norm_path, resolution.get("semantic_kind") or safe_str(obj.type)[:8])
        file_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
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
            can_have_impl = can_have_implementation_kind(resolution.get("semantic_kind"))
            log_info("COMPARE slow-path start: %s | xml=%s | path=%s" % (safe_str(obj.get_name()), is_xml, rel_path))
            ide_content, ide_attrs = get_ide_content(obj, is_xml, property_accessors, projects_obj, can_have_impl)
            log_info("COMPARE slow-path content ready: %s | path=%s" % (safe_str(obj.get_name()), rel_path))
            disk_content = read_file(file_path)

            # For ST files, parse pragmas from disk content for attribute comparison
            disk_attrs = {}
            if not is_xml and disk_content:
                disk_attrs, _ = parse_sync_pragmas(disk_content)

            if contents_are_equal(ide_content, disk_content, is_xml, rel_path, ide_attrs, disk_attrs):
                unchanged_count += 1
                # Update cache
                q_hash = ide_hashes[norm_path] or build_state_hash(ide_content, ide_attrs)
                new_cache_objects[norm_path] = {
                    "ide_hash": q_hash,
                    "disk_hash": calculate_hash(disk_content),
                    "disk_mtime": mtime,
                    "disk_size": size
                }
            else:
                log_info("COMPARE difference detected: %s | path=%s" % (safe_str(obj.get_name()), rel_path))
                full_ide_content = ide_content
                if not is_xml and ide_attrs:
                    full_ide_content = render_sync_pragmas(ide_attrs, ide_content)

                different.append({
                    "name": obj.get_name(), "path": rel_path,
                    "type": type_name, "type_guid": resolution.get("canonical_guid"),
                    "semantic_kind": resolution.get("semantic_kind"),
                    "sync_profile": resolution.get("sync_profile"),
                    "resolution": resolution,
                    "obj": obj, "ide_content": full_ide_content, "disk_content": disk_content,
                    "ide_attrs": ide_attrs, "disk_attrs": disk_attrs
                })
        else:
            new_in_ide.append({
                "name": obj.get_name(), "path": rel_path,
                "type": type_name, "type_guid": resolution.get("canonical_guid"),
                "semantic_kind": resolution.get("semantic_kind"),
                "sync_profile": resolution.get("sync_profile"),
                "resolution": resolution,
                "obj": obj,
                "is_orphan": True
            })

    # Finalize cache with newly built folder hashes and types
    save_sync_cache(base_dir, new_cache_objects, ide_folder_hashes, current_types)
    
    p2_elapsed = time.time() - p2_start
    total_elapsed = time.time() - total_start
    if verbose:
        print("  Pass 2 complete in {:.2f}s".format(p2_elapsed))
        print("  Compare engine finished in {:.2f}s".format(total_elapsed))
    log_info("  Sync cache updated: %d hits, %d entries total" % (cache_hits, len(new_cache_objects)))

    # Pass 3: Disk Scan
    new_on_disk = scan_new_disk_files(base_dir, ide_paths)

    # Pass 4: Detect moved/renamed files
    moved, new_in_ide, new_on_disk = detect_moved_files(new_in_ide, new_on_disk)
    if moved:
        log_info("  Detected %d moved/renamed objects" % len(moved))

    return {
        "different": different,
        "new_in_ide": new_in_ide,
        "new_on_disk": new_on_disk,
        "moved": moved,
        "unchanged_count": unchanged_count,
        "sync_plan": build_sync_plan(different, new_in_ide, new_on_disk, moved, unchanged_count)
    }


def detect_moved_files(new_in_ide, new_on_disk):
    """
    Detect moved/renamed files by cross-referencing objects that exist
    in the IDE but not on disk (new_in_ide) with files on disk that
    don't match any IDE path (new_on_disk).
    
    Matching is done by object base name (case-insensitive).
    
    A "move" is when:
    - IDE has object at path A, but file A doesn't exist on disk
    - Disk has file at path B, but no IDE object maps to path B
    - The base name matches (e.g. same "MyPOU.st" in different folders)
    
    Returns:
        (moved_list, remaining_new_in_ide, remaining_new_on_disk)
        
        moved_list items: {
            "name": str, "ide_path": str, "disk_path": str,
            "type": str, "type_guid": str, "obj": CODESYS obj,
            "file_path": str (absolute), "direction": "ide"|"disk"
        }
    """
    if not new_in_ide or not new_on_disk:
        return [], new_in_ide, new_on_disk
    
    moved = []
    matched_ide_indices = set()
    matched_disk_indices = set()
    
    # Build a lookup from base filename -> list of (index, item) for disk files
    disk_by_name = {}  # base_name_lower -> [(index, item), ...]
    for i, disk_item in enumerate(new_on_disk):
        # Extract base filename from path for matching
        disk_file = disk_item["path"].replace("\\", "/").split("/")[-1]
        base_name = disk_file.lower()
        if base_name not in disk_by_name:
            disk_by_name[base_name] = []
        disk_by_name[base_name].append((i, disk_item))
    
    # Try to match each IDE orphan to a disk orphan by filename
    for ide_idx, ide_item in enumerate(new_in_ide):
        ide_file = ide_item["path"].replace("\\", "/").split("/")[-1]
        base_name = ide_file.lower()
        
        candidates = disk_by_name.get(base_name, [])
        for disk_idx, disk_item in candidates:
            if disk_idx in matched_disk_indices:
                continue
            
            # Match found: same filename, different path
            ide_path = ide_item["path"]
            disk_path = disk_item["path"]
            
            if ide_path == disk_path:
                # Same path — not a move (shouldn't happen but safety check)
                continue
            
            # Determine direction: where is the "correct" location?
            # IDE path = where the object currently lives in IDE
            # Disk path = where the file currently lives on disk
            moved.append({
                "name": ide_item["name"],
                "ide_path": ide_path,
                "disk_path": disk_path,
                "type": ide_item.get("type", "unknown"),
                "type_guid": ide_item.get("type_guid", ""),
                "obj": ide_item.get("obj"),
                "file_path": disk_item.get("file_path", ""),
            })
            
            matched_ide_indices.add(ide_idx)
            matched_disk_indices.add(disk_idx)
            log_info("Detected move: '%s' IDE:'%s' -> Disk:'%s'" % (
                ide_item["name"], ide_path, disk_path))
            break  # One match per IDE item
    
    # Filter out matched items from both lists
    remaining_ide = [item for i, item in enumerate(new_in_ide) if i not in matched_ide_indices]
    remaining_disk = [item for i, item in enumerate(new_on_disk) if i not in matched_disk_indices]
    
    return moved, remaining_ide, remaining_disk


def build_sync_plan(different, new_in_ide, new_on_disk, moved, unchanged_count):
    """Build a normalized sync plan from compare results."""
    modified = []
    for item in different:
        modified.append({
            "name": item.get("name"),
            "path": item.get("path"),
            "type": item.get("type"),
            "semantic_kind": item.get("semantic_kind"),
            "sync_profile": item.get("sync_profile"),
            "type_guid": item.get("type_guid"),
            "resolution": item.get("resolution"),
        })

    ide_only = []
    for item in new_in_ide:
        ide_only.append({
            "name": item.get("name"),
            "path": item.get("path"),
            "type": item.get("type"),
            "semantic_kind": item.get("semantic_kind"),
            "sync_profile": item.get("sync_profile"),
            "type_guid": item.get("type_guid"),
            "resolution": item.get("resolution"),
        })

    disk_only = []
    for item in new_on_disk:
        disk_only.append({
            "name": item.get("name"),
            "path": item.get("path"),
            "file_path": item.get("file_path"),
        })

    moves = []
    for item in moved:
        moves.append({
            "name": item.get("name"),
            "ide_path": item.get("ide_path"),
            "disk_path": item.get("disk_path"),
            "type": item.get("type"),
            "type_guid": item.get("type_guid"),
        })

    return {
        "summary": {
            "modified": len(different),
            "new_in_ide": len(new_in_ide),
            "new_on_disk": len(new_on_disk),
            "moved": len(moved),
            "unchanged": unchanged_count,
        },
        "categories": {
            "modified": modified,
            "ide_only": ide_only,
            "disk_only": disk_only,
            "moved": moves,
        }
    }


def _infer_semantic_kind_from_path(rel_path):
    rel_path = safe_str(rel_path).replace("\\", "/")
    file_name = os.path.basename(rel_path)
    lower_name = file_name.lower()

    if lower_name.endswith(".xml"):
        base_name = file_name[:-4]
        if "." in base_name:
            _, suffix = base_name.rsplit(".", 1)
            suffix = suffix.lower()
            if suffix == "pou_xml":
                return "pou"
            if suffix in SEMANTIC_TYPE_NAMES:
                return suffix

    return None


def _get_import_policy_for_item(item):
    resolution = item.get("resolution")
    if isinstance(resolution, dict) and "import_enabled" in resolution:
        return bool(resolution.get("import_enabled")), resolution

    semantic_kind = item.get("semantic_kind") or _infer_semantic_kind_from_path(item.get("path"))
    if not semantic_kind:
        return True, resolution

    try:
        from codesys_type_system import resolve_runtime_guid
    except ImportError:
        resolve_runtime_guid = _load_sibling_module("codesys_type_system").resolve_runtime_guid

    inferred = resolve_runtime_guid(semantic_kind_to_guid(semantic_kind), profile_name=get_project_prop(PROJECT_PROPERTY_KEY))
    return bool(inferred.get("import_enabled", True)), inferred


def plan_items_for_import(sync_plan):
    """Convert a normalized sync plan into items for disk -> IDE import."""
    if not sync_plan:
        return []

    categories = sync_plan.get("categories", {})
    import_items = []

    for item in categories.get("modified", []):
        import_enabled, resolution = _get_import_policy_for_item(item)
        if not import_enabled:
            continue
        legacy = dict(item)
        if resolution and not legacy.get("resolution"):
            legacy["resolution"] = resolution
        if resolution and not legacy.get("semantic_kind"):
            legacy["semantic_kind"] = resolution.get("semantic_kind")
        legacy["action"] = "update"
        import_items.append(legacy)

    for item in categories.get("disk_only", []):
        import_enabled, resolution = _get_import_policy_for_item(item)
        if not import_enabled:
            continue
        legacy = dict(item)
        if resolution and not legacy.get("resolution"):
            legacy["resolution"] = resolution
        if resolution and not legacy.get("semantic_kind"):
            legacy["semantic_kind"] = resolution.get("semantic_kind")
        legacy["action"] = "create"
        import_items.append(legacy)

    for item in categories.get("ide_only", []):
        import_enabled, resolution = _get_import_policy_for_item(item)
        if not import_enabled:
            continue
        legacy = dict(item)
        if resolution and not legacy.get("resolution"):
            legacy["resolution"] = resolution
        if resolution and not legacy.get("semantic_kind"):
            legacy["semantic_kind"] = resolution.get("semantic_kind")
        legacy["action"] = "delete"
        legacy["is_orphan"] = True
        import_items.append(legacy)

    for item in categories.get("moved", []):
        import_enabled, resolution = _get_import_policy_for_item(item)
        if not import_enabled:
            continue
        legacy = dict(item)
        if resolution and not legacy.get("resolution"):
            legacy["resolution"] = resolution
        if resolution and not legacy.get("semantic_kind"):
            legacy["semantic_kind"] = resolution.get("semantic_kind")
        legacy["action"] = "move"
        legacy["is_moved"] = True
        import_items.append(legacy)

    return import_items


def normalize_sync_items(items, base_dir=None):
    """Normalize mixed sync items into the legacy import item shape."""
    normalized = []
    if not items:
        return normalized

    for item in items:
        if not isinstance(item, dict):
            continue

        action = item.get("action")
        legacy = dict(item)

        if not action:
            if legacy.get("is_orphan"):
                action = "delete"
            elif legacy.get("is_moved"):
                action = "move"
            elif legacy.get("file_path") and not legacy.get("obj"):
                action = "create"
            elif legacy.get("obj"):
                action = "update"

        if action == "ide_only":
            legacy["is_orphan"] = True
            legacy["action"] = "delete"
        elif action == "disk_only":
            legacy.setdefault("file_path", item.get("file_path"))
            legacy["action"] = "create"
        elif action == "modified":
            legacy["action"] = "update"
        elif action == "moved":
            legacy["is_moved"] = True
            legacy["action"] = "move"
        elif action:
            legacy["action"] = action

        if base_dir and not legacy.get("file_path") and legacy.get("path"):
            legacy["file_path"] = os.path.join(base_dir, legacy["path"].replace("/", os.sep))

        if "type_guid" not in legacy:
            legacy["type_guid"] = legacy.get("semantic_kind") or ""

        import_enabled, resolution = _get_import_policy_for_item(legacy)
        if not import_enabled:
            continue

        if resolution and not legacy.get("resolution"):
            legacy["resolution"] = resolution
        if resolution and not legacy.get("semantic_kind"):
            legacy["semantic_kind"] = resolution.get("semantic_kind")

        normalized.append(legacy)

    return normalized


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
                    if doc_type in SEMANTIC_TYPE_NAMES or doc_type == "pou_xml":
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
        "folder": FolderManager(),
        "property": PropertyManager(),
        "task_config": ConfigManager(),
        "alarm_config": ConfigManager(),
        "visu_manager": ConfigManager(),
        "device": ConfigManager(),
        "softmotion_pool": ConfigManager(),
        "default": POUManager(),
        "native": NativeManager()
    }


def resolve_manager(import_managers, type_info, rel_path):
    """Pick the correct manager for a given semantic kind / resolution."""
    if rel_path.endswith(".xml"):
        return import_managers["native"]

    semantic_kind = None
    sync_profile = None
    if isinstance(type_info, dict):
        semantic_kind = type_info.get("semantic_kind") or type_info.get("manager_key")
        sync_profile = type_info.get("sync_profile")
    else:
        semantic_kind = safe_str(type_info).lower()

    kind_key = safe_str(semantic_kind).lower()
    if sync_profile == "native_xml":
        return import_managers["native"]

    mgr = import_managers.get(kind_key)
    if mgr:
        return mgr

    if is_xml_kind(kind_key):
        return import_managers["native"]

    return import_managers["default"]


# Removed update_object_metadata (metadata files no longer used)


def update_existing_object(obj, rel_path, file_path, import_managers):
    """Update an existing IDE object from a disk file."""
    # We no longer use obj_info/metadata hashes. Import always forces content update.
    # managers[type].update already checks for change before applying to IDE.
    profile_name = get_project_prop(PROJECT_PROPERTY_KEY)
    resolved = resolve_runtime_object(obj, profile_name)
    manager = resolve_manager(import_managers, resolved, rel_path)
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
        # XML files are handled by batch_import
        return None
    
    decl, impl, attrs = parse_st_file(file_path)
    content_check = decl if decl else impl
    if not content_check:
        return None
    
    semantic_kind = determine_object_type(content_check)
    
    # Handle nested objects (Action, Method, Property)
    # A dotted base_name like "ST_PROGRAMM.ST_ACTION" means it's a child object.
    name = base_name
    nested_types = ["action", "method", "property", "property_accessor"]
    is_nested = "." in base_name and (semantic_kind in nested_types or not semantic_kind or semantic_kind == "pou")
    if is_nested:
        parts = base_name.rsplit(".", 1)
        parent_name = parts[0]
        child_name = parts[1]
        log_info("Looking for parent POU: " + parent_name + " for child: " + child_name)
        log_info("Name map has " + str(len(name_map)) + " entries")
        pou_parent = find_object_by_name(parent_name, name_map)
        if not pou_parent:
            parent_path = "/".join(path_parts[:-1])
            parent_path_with_name = parent_path + "/" + parent_name
            pou_parent = find_object_by_path(parent_path_with_name, project)
        if not pou_parent:
            log_error("Could not resolve parent POU '" + parent_name + "' for nested object '" + base_name + "'")
            return None

        log_info("Found parent POU: " + safe_str(pou_parent))
        name = child_name
        container = pou_parent
        if not semantic_kind or semantic_kind == "pou":
            upper_child = child_name.upper()
            if upper_child in ("GET", "SET"):
                semantic_kind = "property_accessor"
            else:
                semantic_kind = "action"
    
    resolution = {
        "semantic_kind": semantic_kind,
        "canonical_guid": semantic_kind_to_guid(semantic_kind),
        "manager_key": semantic_kind
    }
    manager = resolve_manager(import_managers, resolution, rel_path)
    res = manager.create(container, name, file_path, semantic_kind, resolution=resolution)
    
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
        [{'name': str, 'semantic_kind': str, 'declaration': str, 'implementation': str}, ...]
    """
    children_info = []
    
    child_types = ["action", "method", "property"]
    
    try:
        for child in pou_obj.get_children():
            try:
                child_type = resolve_runtime_object(child, get_project_prop(PROJECT_PROPERTY_KEY)).get("semantic_kind")
                if child_type in child_types:
                    decl, impl = export_object_content(child)
                    children_info.append({
                        'name': child.get_name(),
                        'semantic_kind': child_type,
                        'declaration': decl,
                        'implementation': impl
                    })
            except Exception as e:
                log_warning("Could not save child " + safe_str(child) + ": " + safe_str(e))
    except Exception as e:
        log_warning("Could not get children of " + safe_str(pou_obj) + ": " + safe_str(e))
    
    return children_info


def _resolve_creation_guid(semantic_kind, profile_name=None, legacy_type_guid=None):
    """Resolve the GUID to use when creating an IDE object."""
    if not semantic_kind and legacy_type_guid:
        semantic_kind = _resolve_kind_value(legacy_type_guid)

    if not semantic_kind:
        return legacy_type_guid

    profile_name = profile_name or get_project_prop(PROJECT_PROPERTY_KEY)
    guid = semantic_kind_to_guid(semantic_kind, profile_name)
    return guid or legacy_type_guid


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
            child_type = child_info.get('semantic_kind')
            legacy_type_guid = child_info.get('type_guid')
            decl = child_info['declaration']
            impl = child_info['implementation']
            profile_name = get_project_prop(PROJECT_PROPERTY_KEY)
            
            existing_child = existing_children.get(child_name.lower())
            
            if existing_child:
                log_info("Restoring child " + child_name + " of " + safe_str(pou_obj))
                if update_object_code(existing_child, decl, impl):
                    log_info("  Successfully updated " + child_name)
            else:
                log_info("Creating child " + child_name + " of " + safe_str(pou_obj))
                try:
                    creation_guid = _resolve_creation_guid(
                        child_type, profile_name, legacy_type_guid
                    )
                    new_child = pou_obj.create_object(
                        name=child_name,
                        type_guid=creation_guid
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
        native_batches: dict of {container: [(rel_path, abs_path, name, semantic_kind, is_new), ...]}
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
                for rel_path, file_path, name, semantic_kind, is_new in items:
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


def finalize_import(project, projects_obj, base_dir, updated_count, created_count, deleted_count=0, moved_count=0):
    """
    Optionally save project + backup.
    Avoids double-save if binary backup is enabled (which already saves).
    """
    if updated_count > 0 or created_count > 0 or deleted_count > 0 or moved_count > 0:
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


def _st_import_sort_key(item):
    """
    Sort ST imports so parent objects are created before nested members.

    This prevents first-pass imports into empty projects from trying to create
    files like `TaskMain.mInit.st` before `TaskMain.st` exists.
    """
    rel_path = safe_str(item.get("path", "")).replace("\\", "/")
    file_name = os.path.basename(rel_path)
    base_name = os.path.splitext(file_name)[0]
    is_nested = "." in base_name
    path_depth = rel_path.count("/")
    return (1 if is_nested else 0, path_depth, rel_path.lower())


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
        (updated_count, created_count, failed_count, deleted_count, moved_count)
    """
    import_managers = create_import_managers()
    to_sync = normalize_sync_items(to_sync, base_dir)
    folder_cache = {}
    name_map = {}
    
    updated_count = 0
    created_count = 0
    deleted_count = 0
    failed_count = 0
    moved_count = 0
    
    native_batches = {}
    st_files_to_import = []
    pou_children_info = {}
    
    # ═══════════════════════════════════════════════════════════════════
    #  PASS 1: Collect XML batches and ST files, save POU children
    # ═══════════════════════════════════════════════════════════════════
    for item in to_sync:
        try:
            action = item.get("action")

            # Handle Deletions
            if action == "delete" or item.get("is_orphan"):
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
                    # ── HANDLE MOVES (XML IMPORT) ──
                    if action == "move" or item.get("is_moved"):
                        target_rel_path = item.get("disk_path")
                        if target_rel_path:
                            path_parts = target_rel_path.split("/")
                            if len(path_parts) > 1:
                                folder_path = "/".join(path_parts[:-1])
                                target_container = ensure_folder_path(folder_path, primary_project)
                                if target_container and target_container != obj.parent:
                                    log_info("Moving XML object '%s' in IDE: %s -> %s" % (
                                        item["name"], item.get("ide_path"), folder_path))
                                    try:
                                        obj.move(target_container)
                                        moved_count += 1
                                    except Exception as me:
                                        log_warning("Failed to move XML %s: %s" % (item["name"], safe_str(me)))

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
                    item.get("semantic_kind") or item.get("type_guid"), is_new
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
        for rel_path, abs_path, name, semantic_kind, is_new in items:
            if semantic_kind == "pou" and not is_new:
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
            for rel_path, abs_path, name, semantic_kind, is_new in items:
                if is_new and semantic_kind == "pou":
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
    st_files_to_import.sort(key=_st_import_sort_key)

    for item in st_files_to_import:
        try:
            action = item.get("action")
            rel_path = item["path"]
            abs_path = item.get("file_path") or os.path.join(base_dir, rel_path.replace("/", os.sep))
            
            if not os.path.exists(abs_path):
                continue
            
            # ST files → find or create
            obj = item.get("obj")
            if not obj:
                obj = find_object_by_path(rel_path, primary_project)

            if obj:
                # ── HANDLE MOVES (IMPORT DIRECTION) ──
                # If disk path doesn't match current IDE path, move the object in IDE
                if action == "move" or item.get("is_moved"):
                    target_rel_path = item.get("disk_path")
                    if target_rel_path:
                        path_parts = target_rel_path.split("/")
                        if len(path_parts) > 1:
                            folder_path = "/".join(path_parts[:-1])
                            target_container = ensure_folder_path(folder_path, primary_project)
                            if target_container and target_container != obj.parent:
                                log_info("Moving object '%s' in IDE: %s -> %s" % (
                                    item["name"], item.get("ide_path"), folder_path))
                                try:
                                    obj.move(target_container)
                                    moved_count += 1
                                except Exception as me:
                                    log_warning("Failed to move %s: %s" % (item["name"], safe_str(me)))

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
                    updated_count, created_count, deleted_count, moved_count)

    return updated_count, created_count, failed_count, deleted_count, moved_count

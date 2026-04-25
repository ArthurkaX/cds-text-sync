# -*- coding: utf-8 -*-
"""
codesys_managers.py - Object Manager classes for CODESYS synchronization

Extracts object-specific logic for export and import operations.
"""
import os
import codecs
import tempfile
import zlib
import time
import sys
import threading

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
from codesys_utils import (
    safe_str, clean_filename, calculate_hash, log_info, log_error, log_warning,
    format_st_content, format_property_content, parse_property_content,
    resolve_projects, is_container_device, get_quick_ide_hash, normalize_path,
    read_ide_attrs, render_sync_pragmas, build_state_hash, get_project_prop
)
try:
    from codesys_type_profiles import PROJECT_PROPERTY_KEY
except ImportError:
    PROJECT_PROPERTY_KEY = _load_sibling_module("codesys_type_profiles").PROJECT_PROPERTY_KEY
try:
    from codesys_type_system import (
        resolve_runtime_object, get_selected_profile_name, semantic_kind_to_guid,
        semantic_kind_from_guid, is_xml_kind, is_exportable_kind,
        can_have_implementation_kind
    )
except ImportError:
    _type_system = _load_sibling_module("codesys_type_system")
    resolve_runtime_object = _type_system.resolve_runtime_object
    get_selected_profile_name = _type_system.get_selected_profile_name
    semantic_kind_to_guid = _type_system.semantic_kind_to_guid
    semantic_kind_from_guid = _type_system.semantic_kind_from_guid
    is_xml_kind = _type_system.is_xml_kind
    is_exportable_kind = _type_system.is_exportable_kind
    can_have_implementation_kind = _type_system.can_have_implementation_kind

# --- Helper Functions ---
_NVL_STATUS_CACHE = {}


def _get_profile_name():
    return get_selected_profile_name(project_profile=get_project_prop(PROJECT_PROPERTY_KEY))


def _get_kind(obj, profile_name=None):
    profile_name = profile_name or _get_profile_name()
    return resolve_runtime_object(obj, profile_name).get("semantic_kind")


def _resolve_kind_value(value):
    if isinstance(value, dict):
        return value.get("semantic_kind") or value.get("manager_key") or value.get("canonical_guid") or value.get("type_guid")
    value = safe_str(value).lower()
    if not value:
        return ""
    resolved = semantic_kind_from_guid(value, _get_profile_name())
    if resolved:
        return resolved
    return value


_MONOLITHIC_NATIVE_KINDS = set([
    "task_config", "alarm_config", "visu_manager", "softmotion_pool"
])


def get_native_snapshot_recursive(obj, resolution=None):
    """Return the canonical recursive export policy for native XML snapshots."""
    resolution = resolution or resolve_runtime_object(obj, get_project_prop(PROJECT_PROPERTY_KEY))
    semantic_kind = (resolution or {}).get("semantic_kind")

    if semantic_kind in _MONOLITHIC_NATIVE_KINDS:
        return True

    if semantic_kind == "device":
        return not is_container_device(obj)

    return False


def export_native_snapshot(obj, target_path, projects_obj=None, resolution=None, recursive=None):
    """Export one IDE object to native XML using the shared snapshot policy."""
    resolution = resolution or resolve_runtime_object(obj, get_project_prop(PROJECT_PROPERTY_KEY))
    projects_obj = projects_obj or resolve_projects()
    project = getattr(projects_obj, "primary", None) if projects_obj else None
    if not project:
        raise RuntimeError("Native export failed: 'projects' object not found or no primary project.")

    if recursive is None:
        recursive = get_native_snapshot_recursive(obj, resolution)
    project.export_native([obj], target_path, recursive=recursive)

    return {
        "semantic_kind": (resolution or {}).get("semantic_kind"),
        "recursive": recursive,
        "content_hash": NativeManager()._hash_file(target_path)
    }


def build_native_xml_snapshot(obj, projects_obj=None, resolution=None, temp_prefix="cds_native_snapshot_"):
    """Build an in-memory native XML snapshot plus its normalized hash."""
    fd, tmp_path = tempfile.mkstemp(prefix=temp_prefix, suffix=".xml")
    os.close(fd)
    try:
        os.remove(tmp_path)
    except:
        pass

    try:
        meta = export_native_snapshot(obj, tmp_path, projects_obj=projects_obj, resolution=resolution)
        with codecs.open(tmp_path, "r", "utf-8") as stream:
            return stream.read(), meta
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

def get_task_for_write(obj, project):
    """
    Extract the 'TaskForWrite' (assigned task) GUID from a Task Local GVL
    by exporting it to native XML and parsing the TaskForWrite field.
    Returns (task_guid, task_name) or (None, None) if not found.
    """
    import tempfile, re
    try:
        tmp_path = os.path.join(tempfile.gettempdir(), "tlgvl_%s.xml" % safe_str(obj.guid)[:8])
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        project.export_native([obj], tmp_path, recursive=False)

        if not os.path.exists(tmp_path):
            return None, None

        import codecs as _codecs
        with _codecs.open(tmp_path, "r", "utf-8") as xf:
            xml_content = xf.read()
        os.remove(tmp_path)

        # Parse <Single Name="TaskForWrite" Type="System.Guid">GUID</Single>
        match = re.search(r'<Single Name="TaskForWrite" Type="System\.Guid">([^<]+)</Single>', xml_content)
        if not match:
            return None, None

        task_guid = match.group(1).strip()

        # Look up the task name by GUID in the project
        task_name = task_guid  # fallback to GUID if name not found
        try:
            all_objs = project.get_children(recursive=True)
            for candidate in all_objs:
                if safe_str(candidate.guid) == task_guid:
                    task_name = safe_str(candidate.get_name())
                    break
        except:
            pass

        return task_guid, task_name

    except Exception as e:
        log_warning("Could not extract TaskForWrite for " + safe_str(obj.get_name()) + ": " + safe_str(e))
        return None, None

def is_nvl(obj):
    """
    Detect if a GVL object is actually a Network Variable List (NVL).
    
    CODESYS reports NVLs with the same type GUID as standard GVLs.
    The only way to distinguish them is by exporting to native XML 
    and checking for NVL-specific elements like ListIdentifier or NetworkType.
    
    Returns True if the object is an NVL, False otherwise.
    """
    obj_guid = safe_str(getattr(obj, "guid", ""))
    if obj_guid in _NVL_STATUS_CACHE:
        return _NVL_STATUS_CACHE[obj_guid]

    if threading.current_thread() is not threading.main_thread():
        log_info("Skipping NVL native probe on background thread for " + safe_str(obj.get_name()))
        _NVL_STATUS_CACHE[obj_guid] = False
        return False

    import tempfile, re
    try:
        projects_obj = resolve_projects()
        if not projects_obj or not projects_obj.primary:
            _NVL_STATUS_CACHE[obj_guid] = False
            return False
            
        tmp_path = os.path.join(tempfile.gettempdir(), "nvl_check_%s.xml" % safe_str(obj.guid)[:8])
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        projects_obj.primary.export_native([obj], tmp_path, recursive=False)

        if not os.path.exists(tmp_path):
            _NVL_STATUS_CACHE[obj_guid] = False
            return False

        import codecs as _codecs
        with _codecs.open(tmp_path, "r", "utf-8") as xf:
            xml_content = xf.read()
        os.remove(tmp_path)

        # NVL XML contains ListIdentifier and/or NetworkType elements
        if 'ListIdentifier' in xml_content or 'NetworkType' in xml_content:
            _NVL_STATUS_CACHE[obj_guid] = True
            return True
        
        _NVL_STATUS_CACHE[obj_guid] = False
        return False

    except Exception as e:
        log_warning("Could not check NVL status for " + safe_str(obj.get_name()) + ": " + safe_str(e))
        _NVL_STATUS_CACHE[obj_guid] = False
        return False

def is_graphical_pou(obj):
    """
    Detect if a POU uses a graphical language (LD, CFC, FBD) instead of ST/IL.

    CODESYS assigns the same type GUID to all POUs regardless of language.
    The distinguishing factor is that graphical POUs do NOT have a textual
    implementation body — the implementation exists only in the native XML
    (graphical data). ST/IL POUs always have has_textual_implementation=True.

    Returns True if the POU's implementation is graphical (needs XML export),
    False if it is text-based (ST/IL, can be exported as .st).
    """
    try:
        # If the object explicitly has a textual implementation, it is ST/IL
        if hasattr(obj, 'has_textual_implementation'):
            return not obj.has_textual_implementation
        # If the attribute is missing we cannot determine — treat as textual (safe default)
        return False
    except Exception as e:
        log_warning("Could not check graphical POU status for " + safe_str(obj.get_name()) + ": " + safe_str(e))
        return False

def get_object_path(obj, stop_at_application=True):
    """
    Build the path from object to Application root.
    Returns list of folder names from Application (exclusive) to object (exclusive).
    """
    path_parts = []
    current = obj
    
    while current is not None:
        try:
            if not hasattr(current, "parent") or current.parent is None:
                break
            
            parent = current.parent
            if not hasattr(parent, "type") or not hasattr(parent, "get_name"):
                break

            parent_kind = _get_kind(parent)
            if stop_at_application and parent_kind == "application":
                break

            if parent_kind in ["plc_logic", "device"]:
                break

            # Skip Task Configuration and individual Tasks in path building
            # Tasks are exported as monolithic Task Configuration XML,
            # so their children should not create Task subfolders on disk
            if parent_kind in ["task_config", "task"]:
                break
            
            parent_name = clean_filename(parent.get_name())
            path_parts.insert(0, parent_name)
            current = parent
        except:
            break
    return path_parts

def get_container_prefix(obj):
    """Walk up from obj to find its Device and Application names.
    Returns list like ['PLC', 'ST_Application'] or [] for global objects."""
    parts = []
    current = obj
    app_name = None
    device_name = None
    
    # We walk up to the root to find the containing app and device
    while current is not None:
        try:
            curr_kind = _get_kind(current)
            if curr_kind == "application":
                app_name = clean_filename(current.get_name())
            elif curr_kind == "device":
                device_name = clean_filename(current.get_name())
            
            if not hasattr(current, "parent"): break
            current = current.parent
        except: break
        
    if device_name: parts.append(device_name)
    if app_name: parts.append(app_name)
    return parts

def get_parent_pou_name(obj):
    """Get parent POU/Interface name for nested objects (actions, methods, properties)"""
    try:
        if hasattr(obj, "parent") and obj.parent:
            if not hasattr(obj.parent, "type") or not hasattr(obj.parent, "get_name"):
                return None
            parent_kind = _get_kind(obj.parent)
            if parent_kind in ["pou", "itf"]:
                return obj.parent.get_name()
    except:
        pass
    return None

def build_expected_path(obj, resolution, is_xml=None):
    """Build the expected rel_path for an IDE object.
    
    Args:
        obj: The CODESYS IDE object
        resolution: A resolution dict (from classify_object or resolve_runtime_object)
                    containing semantic_kind, sync_profile, is_xml, etc.
        is_xml: DEPRECATED - kept for backward compatibility. If provided, 
                overrides the resolution-derived value.
    
    The function now derives is_xml from resolution.sync_profile == "native_xml"
    or resolution.is_xml, rather than requiring a separate boolean parameter.
    """
    effective_kind = _resolve_kind_value(resolution)
    container = get_container_prefix(obj)
    path_parts = get_object_path(obj)
    obj_name = obj.get_name()
    clean_name = clean_filename(obj_name)
    obj_kind = _get_kind(obj)
    if is_xml is not None:
        derived_is_xml = bool(is_xml)
    elif isinstance(resolution, dict):
        sync_profile = resolution.get("sync_profile", "")
        derived_is_xml = (sync_profile == "native_xml") or bool(resolution.get("is_xml", False))
    else:
        derived_is_xml = False
    is_xml = derived_is_xml

    if is_xml:
        # Special case: POUs exported as XML (graphical) use 'pou_xml' extension
        if effective_kind == "pou":
            type_name = "pou_xml"
        else:
            type_name = effective_kind or safe_str(effective_type)[:8]
        file_name = clean_name + "." + type_name + ".xml"
    else:
        parent_pou = get_parent_pou_name(obj)
        # Nested objects (Action, Method, Property) prefix filename with parent POU name
        if parent_pou and obj_kind in ["action", "method", "property", "itf_method"]:
            file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
            clean_parent_pou = clean_filename(parent_pou)
            # If the path already has the parent name as a folder, remove it to avoid redundancy
            if path_parts and path_parts[-1] == clean_parent_pou:
                path_parts = path_parts[:-1]
        elif obj_kind == "folder":
            # Folders use their own name as the last part of path
            file_name = ""
        else:
            file_name = clean_name + ".st"

    full_path_parts = container + path_parts
    if not file_name:
        return "/".join(full_path_parts)
    
    if full_path_parts:
        return "/".join(full_path_parts) + "/" + file_name
    return file_name

def export_interface_declaration(obj):
    """Extract interface declaration via native XML export fallback."""
    import re
    try:
        projects_obj = resolve_projects()
        if not projects_obj or not projects_obj.primary:
            return None
            
        tmp_path = os.path.join(tempfile.gettempdir(), "itf_%s.xml" % safe_str(obj.guid)[:8])
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        projects_obj.primary.export_native([obj], tmp_path, recursive=False)

        if not os.path.exists(tmp_path):
            return None

        with codecs.open(tmp_path, "r", "utf-8") as xf:
            xml_content = xf.read()
        os.remove(tmp_path)

        match = re.search(r'<Declaration><!\[CDATA\[(.*?)\]\]></Declaration>', xml_content, re.DOTALL)
        if match:
            return match.group(1).strip()
    except Exception as e:
        log_warning("Could not extract interface declaration for " + safe_str(obj.get_name()) + ": " + safe_str(e))
    return None

def export_object_content(obj):
    """Extract declaration and implementation text from object."""
    declaration = None
    implementation = None
    try:
        if hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
            declaration = obj.textual_declaration.text
    except: pass
    
    if declaration is None and _get_kind(obj) == "itf":
        declaration = export_interface_declaration(obj)
    
    try:
        if hasattr(obj, "has_textual_implementation") and obj.has_textual_implementation:
            implementation = obj.textual_implementation.text
    except: pass
    return declaration, implementation

def update_object_code(obj, declaration, implementation):
    """Update object's textual declaration and/or implementation.
    
    Handles multiple CODESYS versions:
    - Some allow direct .text assignment
    - Some have read-only .text but support .replace(new_content) with a single string arg
    """
    updated = False
    try:
        if declaration is not None and hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
            doc = obj.textual_declaration
            if doc.text != declaration:
                try:
                    doc.text = declaration
                    updated = True
                except:
                    # Fallback: ScriptTextDocument.replace(new_content)
                    # takes a single string argument to replace the entire content
                    doc.replace(declaration)
                    updated = True

        if implementation is not None and hasattr(obj, "has_textual_implementation") and obj.has_textual_implementation:
            doc = obj.textual_implementation
            if doc.text != implementation:
                try:
                    doc.text = implementation
                    updated = True
                except:
                    doc.replace(implementation)
                    updated = True
    except Exception as e:
        log_error("Error updating " + safe_str(obj.get_name()) + ": " + safe_str(e))
    return updated

def parse_accessor_content(combined_content):
    """Split combined accessor content into (declaration, implementation).
    
    Args:
        combined_content: String containing declaration and optionally
                          IMPL_MARKER followed by implementation code.
    
    Returns:
        tuple: (declaration, implementation) — implementation may be None.
    """
    from codesys_constants import IMPL_MARKER
    if IMPL_MARKER in combined_content:
        parts = combined_content.split(IMPL_MARKER, 1)
        decl = parts[0].strip()
        code = parts[1].strip() if len(parts) > 1 else None
        return decl, code
    return combined_content.strip(), None

def collect_property_accessors(all_objects):
    """Collect property Get/Set accessors grouped by parent property GUID.
    
    Uses two passes:
    1. Scan all objects for property_accessor type
    2. Check each property's children directly (fallback)
    
    Returns:
        dict: {property_guid: {'get': obj|None, 'set': obj|None, 'parent_obj': obj}}
    """
    property_accessors = {}
    
    # Pass 1: Find accessors by type
    for obj in all_objects:
        try:
            if not hasattr(obj, 'type') or not hasattr(obj, 'get_name'):
                continue
            obj_type = safe_str(obj.type)
            if _resolve_kind_value(obj_type) == "property_accessor":
                if hasattr(obj, "parent") and obj.parent:
                    parent_type = safe_str(obj.parent.type)
                    if _resolve_kind_value(parent_type) == "property":
                        parent_guid = safe_str(obj.parent.guid)
                        if parent_guid not in property_accessors:
                            property_accessors[parent_guid] = {
                                'get': None, 'set': None, 'parent_obj': obj.parent
                            }
                        name = obj.get_name().lower()
                        if name == "get":
                            property_accessors[parent_guid]['get'] = obj
                        elif name == "set":
                            property_accessors[parent_guid]['set'] = obj
        except:
            continue
    
    # Pass 2: Check property children directly
    for obj in all_objects:
        try:
            if not hasattr(obj, 'type'):
                continue
            obj_type = safe_str(obj.type)
            if _resolve_kind_value(obj_type) == "property":
                obj_guid = safe_str(obj.guid)
                try:
                    if obj_guid not in property_accessors:
                        property_accessors[obj_guid] = {
                            'get': None, 'set': None, 'parent_obj': obj
                        }
                    children = obj.get_children()
                    for child in children:
                        child_type = safe_str(child.type)
                        if _resolve_kind_value(child_type) == "property_accessor":
                            child_name = child.get_name().lower()
                            if child_name == "get":
                                property_accessors[obj_guid]['get'] = child
                            elif child_name == "set":
                                property_accessors[obj_guid]['set'] = child
                except:
                    pass
        except:
            continue
    
    return property_accessors

def classify_object(obj):
    """
    Determine the effective export type for a CODESYS object.

    Returns:
        resolution dict with semantic kind, sync profile and legacy compatibility fields.
    """
    profile_name = _get_profile_name()
    resolution = resolve_runtime_object(obj, profile_name)
    obj_type = safe_str(obj.type)
    semantic_kind = resolution.get("semantic_kind")
    effective_type = resolution.get("canonical_guid") or obj_type
    is_xml = bool(resolution.get("is_xml"))
    should_skip = False

    if not resolution.get("export_enabled", True):
        should_skip = True

    # Skip non-exportable
    if semantic_kind == "property_accessor":
        should_skip = True
    if semantic_kind == "task":
        should_skip = True

    # Skip all children of monolithic containers - they are exported as
    # recursive XML with their parent. Prevents duplicate export/sync.
    # Logic for devices: Containers (PLCs) are NOT monolithic, so we don't
    # skip their children (Applications and sub-devices).
    monolithic_kinds = ["alarm_config", "visu_manager", "task_config", "softmotion_pool"]
    try:
        parent_kind = _get_kind(obj.parent, profile_name) if hasattr(obj, 'parent') and obj.parent else ""
        if parent_kind in monolithic_kinds:
            should_skip = True
            
        # Device recursion check:
        # If parent is a device, we only skip if the parent IS a monolithic unit.
        if parent_kind == "device":
            if not is_container_device(obj.parent):
                # Parent is functional device (monolithic), so skip children.
                should_skip = True
    except:
        pass

    # Skip per-POU alarm groups/classes — these are auto-generated children of
    # POUs and can't be independently exported. Only alarm groups under the
    # Alarm Configuration tree are valid standalone exports.
    if semantic_kind in ["alarm_group", "alarm_class"]:
        try:
            parent_kind = _get_kind(obj.parent, profile_name)
            if parent_kind != "alarm_config":
                should_skip = True
        except:
            pass

    # Skip auto-generated VisualizationStyle objects
    # These are created by CODESYS at multiple locations (Visualization Manager,
    # Application root, project root) and should never be exported/synced.
    if semantic_kind == "visu_style":
        should_skip = True

    # NVL detection: GVL that is actually a Network Variable List
    if semantic_kind == "gvl":
        try:
            if is_nvl(obj):
                semantic_kind = "nvl_sender"
                effective_type = semantic_kind_to_guid(semantic_kind, profile_name) or effective_type
                is_xml = True
                resolution["semantic_kind"] = semantic_kind
                resolution["canonical_guid"] = effective_type
                resolution["sync_profile"] = "native_xml"
                resolution["creation_strategy"] = "create_child"
                resolution["evidence"] = list(resolution.get("evidence") or []) + ["nvl_detected"]
        except:
            pass

    # Graphical POU detection (LD, CFC, FBD → XML)
    if not is_xml and semantic_kind in ["pou", "action", "method"]:
        try:
            if is_graphical_pou(obj):
                is_xml = True
        except:
            pass

    # Semantic XML kinds are always XML
    if is_xml_kind(semantic_kind):
        is_xml = True

    # Check if type is exportable at all
    if semantic_kind and not is_exportable_kind(semantic_kind) and not is_xml_kind(semantic_kind):
        should_skip = True

    resolution.update({
        "effective_type": effective_type,
        "is_xml": is_xml,
        "should_skip": should_skip,
        "manager_key": semantic_kind or effective_type,
        "type_guid": effective_type,
    })
    return resolution

# --- Manager Classes ---

class ObjectManager(object):
    """Base class for managing CODESYS objects"""
    def _update_cache_entry(self, obj, rel_path, file_path, context, q_hash=None, stat_info=None):
        """Update the shared context cache with latest object metadata."""
        if 'new_cache' not in context or not os.path.exists(file_path):
            return
        
        norm_path = normalize_path(rel_path)
        try:
            s = stat_info if stat_info else os.stat(file_path)
            if q_hash is None:
                q_hash = get_quick_ide_hash(obj, False)

            if not q_hash:
                log_warning("Cache entry skipped for %s: empty ide_hash (%s)" % (
                    safe_str(obj.get_name()) if obj and hasattr(obj, "get_name") else "<unknown>",
                    rel_path
                ))
                return

            context['new_cache'][norm_path] = {
                "ide_hash": q_hash,
                "disk_mtime": int(s.st_mtime),
                "disk_size": s.st_size
            }
        except Exception as e:
            log_warning("Failed to update cache entry for %s (%s): %s" % (
                safe_str(obj.get_name()) if obj and hasattr(obj, "get_name") else "<unknown>",
                rel_path,
                safe_str(e)
            ))

    def _try_cache_skip(self, obj, rel_path, file_path, context, is_xml=False):
        """Attempt to skip export via IDE-cache-disk fast path.

        Returns "identical" if skip succeeds, None otherwise.
        """
        norm_path = normalize_path(rel_path)
        cache = context.get('cache_data')
        if not cache:
            return None

        q_hash = get_quick_ide_hash(obj, is_xml)
        cached_obj = cache.get('objects', {}).get(norm_path)
        if not (q_hash and cached_obj and cached_obj.get('ide_hash') == q_hash):
            return None

        if not os.path.exists(file_path):
            return None

        s = os.stat(file_path)
        if int(s.st_mtime) != cached_obj.get('disk_mtime') or s.st_size != cached_obj.get('disk_size'):
            return None

        if 'exported_paths' in context:
            context['exported_paths'].add(rel_path)
        self._update_cache_entry(obj, rel_path, file_path, context, q_hash, s)
        return "identical"

    def export(self, obj, context, rel_path=None):
        """Export object to file system and update metadata"""
        pass
    
    def update(self, obj, file_path, obj_info):
        """Update existing object from file system"""
        pass
    
    def create(self, container, name, file_path, type_guid, resolution=None):
        """Create new object from file system"""
        pass

class FolderManager(ObjectManager):
    """Handle folder creation and management"""
    def export(self, obj, context, rel_path=None):
        if rel_path is None:
            resolution = context.get("resolution") or {"semantic_kind": "folder", "sync_profile": "textual"}
            rel_path = build_expected_path(obj, resolution)
        
        # Track and cache
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        if 'exported_paths' in context:
            context['exported_paths'].add(rel_path)
        
        # Folders use a constant hash since we just want to track their path/mtime
        self._update_cache_entry(obj, rel_path, file_path, context, q_hash="folder")

        # Skip creating folders for special XML containers
        if _get_kind(obj) in ["task_config", "alarm_config"]:
            return "identical"
            
        return "identical"

    def update(self, obj, file_path, obj_info=None):
        # Folders don't have textual content to update
        return False

    def create(self, container, name, file_path, type_guid, resolution=None):
        # For folders, container should be the parent folder/application
        # But we also have absolute path in file_path (which is relative in metadata)
        from codesys_utils import ensure_folder_path
        try:
            # In CODESYS, 'projects' is an environment global, no need to import it
            # file_path in this context is the rel_path from metadata e.g. "src/Folder/Sub"
            projects_obj = resolve_projects()
            if projects_obj and projects_obj.primary:
                return ensure_folder_path(file_path, projects_obj.primary)
            return None
        except:
            return None

class POUManager(ObjectManager):
    """Handle standard textual objects (POUs, GVLs, DUTs)"""
    def export(self, obj, context, rel_path=None):
        # Build path and filename
        if rel_path is None:
            resolution = context.get("resolution") or {"semantic_kind": context.get('effective_type', safe_str(obj.type)), "sync_profile": "textual"}
            rel_path = build_expected_path(obj, resolution)
        
        # Determine target directory and file path
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        target_dir = os.path.dirname(file_path)
        file_name = os.path.basename(rel_path)
        
        # --- CACHE SKIP OPTIMIZATION ---
        skip = self._try_cache_skip(obj, rel_path, file_path, context, is_xml=False)
        if skip:
            return skip
        # -------------------------------

        declaration, implementation = export_object_content(obj)
        # Check if this object type can have implementation even if empty
        obj_type_guid = safe_str(obj.type)
        obj_kind = _get_kind(obj)
        can_have_impl = can_have_implementation_kind(obj_kind)
        clean_content = format_st_content(declaration, implementation, can_have_impl)
        
        if not clean_content.strip():
            return False
        
        # Read IDE attributes and render sync pragmas
        attrs = read_ide_attrs(obj)
        content = render_sync_pragmas(attrs, clean_content)
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        
        content_hash = build_state_hash(clean_content, attrs)
        is_new = not os.path.exists(file_path)
        
        # Check if content is identical to existing file
        if not is_new:
            try:
                with codecs.open(file_path, "r", "utf-8") as f:
                    existing_content = f.read()
                if calculate_hash(existing_content) == calculate_hash(content):
                    # Track path and return
                    if 'exported_paths' in context:
                        context['exported_paths'].add(rel_path)
                    
                    self._update_cache_entry(obj, rel_path, file_path, context, content_hash)
                    return "identical"
            except:
                pass  # If we can't read existing file, just overwrite
            
        try:
            with codecs.open(file_path, "w", "utf-8") as f:
                f.write(content)
        except Exception as e:
            log_error("Failed to write ST file " + file_name + ": " + safe_str(e))
            return False
            
        if 'exported_paths' in context:
            context['exported_paths'].add(rel_path)
        self._update_cache_entry(obj, rel_path, file_path, context, content_hash)
        return "new" if is_new else "updated"

    def update(self, obj, file_path, obj_info=None):
        from codesys_utils import parse_st_file, parse_sync_pragmas, write_ide_attrs
        declaration, implementation, attrs = parse_st_file(file_path)
        if declaration is None and implementation is None:
            return False
        
        updated = update_object_code(obj, declaration, implementation)
        write_ide_attrs(obj, attrs)
        return updated

    def create(self, container, name, file_path, type_guid, resolution=None):
        from codesys_utils import parse_st_file, write_ide_attrs
        declaration, implementation, attrs = parse_st_file(file_path)
        
        obj = None
        semantic_kind = None
        canonical_guid = None
        profile_name = _get_profile_name()
        if isinstance(resolution, dict):
            semantic_kind = resolution.get("semantic_kind")
            canonical_guid = resolution.get("canonical_guid")
            profile_name = resolution.get("profile_name") or profile_name
        if not semantic_kind:
            semantic_kind = _resolve_kind_value(type_guid)
        if not canonical_guid:
            canonical_guid = semantic_kind_to_guid(semantic_kind, profile_name)
        try:
            if semantic_kind in ["gvl", "task_local_gvl", "persistent_gvl"] and hasattr(container, "create_gvl"):
                obj = container.create_gvl(name)
            elif semantic_kind == "dut" and hasattr(container, "create_dut"):
                obj = container.create_dut(name)
            elif semantic_kind == "itf" and hasattr(container, "create_interface"):
                obj = container.create_interface(name)
            elif semantic_kind == "method" and hasattr(container, "create_method"):
                obj = container.create_method(name)
            elif semantic_kind == "property" and hasattr(container, "create_property"):
                obj = container.create_property(name)
            elif semantic_kind == "action" and hasattr(container, "create_action"):
                obj = container.create_action(name)
            elif hasattr(container, "create_pou"):
                # Always create as Program first — update_object_code will replace
                # the declaration with the correct FUNCTION / FUNCTION_BLOCK header.
                # PouType is a CODESYS global (like 'projects', 'system'), NOT an import.
                p_type = None
                # Strategy 1: Direct global (how it works in CODESYS environment)
                try:
                    p_type = PouType.Program
                except NameError:
                    pass
                # Strategy 2: __main__ module
                if p_type is None:
                    try:
                        import __main__
                        p_type = __main__.PouType.Program
                    except:
                        pass
                # Strategy 3: ScriptEngine import
                if p_type is None:
                    try:
                        from ScriptEngine import PouType as _PT
                        p_type = _PT.Program
                    except:
                        pass
                # Strategy 4: sys.modules scan
                if p_type is None:
                    try:
                        for mod in sys.modules.values():
                            if hasattr(mod, "PouType"):
                                p_type = mod.PouType.Program
                                break
                    except:
                        pass

                if p_type is not None:
                    obj = container.create_pou(name, p_type)
                else:
                    log_error("Cannot resolve PouType enum. Falling back to create_child.")
                    fallback_guid = canonical_guid or semantic_kind_to_guid(semantic_kind, profile_name) or type_guid
                    obj = container.create_child(name, fallback_guid) if hasattr(container, "create_child") else None
            elif hasattr(container, "create_child"):
                fallback_guid = canonical_guid or semantic_kind_to_guid(semantic_kind, profile_name) or type_guid
                obj = container.create_child(name, fallback_guid)
                
            if obj:
                update_object_code(obj, declaration, implementation)
                write_ide_attrs(obj, attrs)
                return obj
        except Exception as e:
            log_error("Failed to create " + name + ": " + safe_str(e))
        return None

class PropertyManager(POUManager):
    """Handle properties specifically (combining declaration, Get, and Set)"""
    def export(self, obj, context, rel_path=None):
        obj_guid = safe_str(obj.guid)
        
        if obj_guid not in context['property_accessors']:
            prop_data = {'get': None, 'set': None, 'parent_obj': obj}
        else:
            prop_data = context['property_accessors'][obj_guid]
        
        if rel_path is None:
            resolution = context.get("resolution") or {"semantic_kind": context.get('effective_type', safe_str(obj.type)), "sync_profile": "textual"}
            rel_path = build_expected_path(obj, resolution)
        
        # Determine target directory and file path
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        target_dir = os.path.dirname(file_path)
        file_name = os.path.basename(rel_path)
        
        # --- CACHE SKIP OPTIMIZATION ---
        skip = self._try_cache_skip(obj, rel_path, file_path, context, is_xml=False)
        if skip:
            return skip
        # -------------------------------
        
        obj_name = obj.get_name()

        # Export Declaration
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
            
        # Export even if implementations are empty
            
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        # Combine into Property Format
        combined_content = format_property_content(declaration, get_impl, set_impl)
        
        # Read IDE attributes and render sync pragmas
        attrs = read_ide_attrs(obj)
        content = render_sync_pragmas(attrs, combined_content)
        content_hash = build_state_hash(combined_content, attrs)
        
        is_new = not os.path.exists(file_path)
        
        # Check if content is identical to existing file
        if not is_new:
            try:
                with codecs.open(file_path, "r", "utf-8") as f:
                    existing_content = f.read()
                if calculate_hash(existing_content) == calculate_hash(content):
                    if 'exported_paths' in context:
                        context['exported_paths'].add(rel_path)
                    
                    self._update_cache_entry(obj, rel_path, file_path, context, content_hash)
                    return "identical"
            except:
                pass
        
        try:
            with codecs.open(file_path, "w", "utf-8") as f:
                f.write(content)
        except Exception as e:
            log_error("Failed to write Property file " + file_name + ": " + safe_str(e))
            return False
            
        if 'exported_paths' in context:
            context['exported_paths'].add(rel_path)
        self._update_cache_entry(obj, rel_path, file_path, context, content_hash)
        return "new" if is_new else "updated"

    def update(self, obj, file_path, obj_info=None):
        try:
            with codecs.open(file_path, "r", "utf-8") as f:
                raw_content = f.read()
        except: return False
        
        from codesys_utils import parse_sync_pragmas, write_ide_attrs
        attrs, clean_content = parse_sync_pragmas(raw_content.replace('\r\n', '\n').replace('\r', '\n'))
        
        declaration, get_impl_combined, set_impl_combined = parse_property_content(clean_content)
        updated = False
        
        if declaration and update_object_code(obj, declaration, None):
            updated = True
            
        # Update GET accessor
        if get_impl_combined:
            for child in obj.get_children():
                if child.get_name().lower() == "get":
                    g_decl, g_code = parse_accessor_content(get_impl_combined)
                    if update_object_code(child, g_decl, g_code):
                        updated = True
                    break
                    
        # Update SET accessor
        if set_impl_combined:
            for child in obj.get_children():
                if child.get_name().lower() == "set":
                    s_decl, s_code = parse_accessor_content(set_impl_combined)
                    if update_object_code(child, s_decl, s_code):
                        updated = True
                    break
        
        if attrs:
            write_ide_attrs(obj, attrs)
        
        return updated

    def create(self, container, name, file_path, type_guid, resolution=None):
        try:
            with codecs.open(file_path, "r", "utf-8") as f:
                raw_content = f.read()
        except: return None
        
        from codesys_utils import parse_sync_pragmas, write_ide_attrs
        attrs, clean_content = parse_sync_pragmas(raw_content.replace('\r\n', '\n').replace('\r', '\n'))
        
        declaration, get_impl_combined, set_impl_combined = parse_property_content(clean_content)
        
        obj = None
        try:
            if hasattr(container, "create_property"):
                obj = container.create_property(name)
            elif hasattr(container, "create_child"):
                canonical_guid = None
                if isinstance(resolution, dict):
                    canonical_guid = resolution.get("canonical_guid")
                    profile_name = resolution.get("profile_name") or _get_profile_name()
                else:
                    profile_name = _get_profile_name()
                fallback_guid = canonical_guid or semantic_kind_to_guid(_resolve_kind_value(type_guid), profile_name) or type_guid
                obj = container.create_child(name, fallback_guid)
                
            if obj:
                if declaration:
                    update_object_code(obj, declaration, None)
                
                if get_impl_combined and hasattr(obj, "create_get_accessor"):
                    get_obj = obj.create_get_accessor()
                    g_decl, g_code = parse_accessor_content(get_impl_combined)
                    update_object_code(get_obj, g_decl, g_code)
                    
                if set_impl_combined and hasattr(obj, "create_set_accessor"):
                    set_obj = obj.create_set_accessor()
                    s_decl, s_code = parse_accessor_content(set_impl_combined)
                    update_object_code(set_obj, s_decl, s_code)
                
                if attrs:
                    write_ide_attrs(obj, attrs)
                
                return obj
        except Exception as e:
            log_error("Failed to create property " + name + ": " + safe_str(e))
        return None

class NativeManager(ObjectManager):
    """Handle objects exported as native CODESYS XML"""
    def _hash_file(self, file_path):
        """Calculate CRC32 hash of a file's content, ignoring dynamic bits like timestamps."""
        try:
            with codecs.open(file_path, "r", "utf-8") as f:
                content_full = f.read()
                lines = content_full.splitlines(True)  # Keep line endings
            
            # Detect if this is an AlarmGroup-related file that can have type conversions
            is_alarm_group = 'AlarmGroup' in content_full and 'GlobalTextList' not in content_full
            is_textlist = '<Single Name="Name" Type="string">GlobalTextList' in content_full
            is_alarm_config = 'Alarm Configuration' in content_full
            is_device = '225bfe47-7336-4dbc-9419-4105a7c831fa' in content_full or '<Device' in content_full
            
            # Special handling for AlarmGroup and GlobalTextList: filter out dynamic content
            if is_alarm_group or is_textlist or is_alarm_config or is_device:
                # Extract only stable metadata that shouldn't change
                stable_content = []
                for line in lines:
                    # Filter out timestamps and dynamic GUIDs for all these types
                    if 'Name="Timestamp"' in line: continue
                    if 'Name="Guid"' in line and 'Type="System.Guid"' in line: continue
                    if '<Timestamp>' in line: continue # Device specific timestamp
                    
                    # For GlobalTextList, keep most content except dynamic parts
                    if is_textlist:
                        stable_content.append(line)
                    # For devices, we want to keep most content but be wary of dynamic IDs
                    elif is_device:
                        # Skip lines that look like dynamic IDs or timestamps
                        if 'vqid' in line.lower() or 'instanceid' in line.lower(): continue
                        stable_content.append(line)
                    # For AlarmGroup, keep only basic identifying information  
                    elif is_alarm_group:
                        if '<Single Name="Name" Type="string">' in line and 'AlarmGroup' in line:
                            stable_content.append(line)
                        elif 'CODESYS_HMI' in line and 'HMI_Application' in line and 'Alarm Configuration' in line:
                            stable_content.append(line)
                        # Also keep the object type identifier for more precise comparison
                        elif '<Object Guid="' in line and ('Type="type_21f"' in line or 'Type="textlist"' in line):
                            stable_content.append(line)
                    elif is_alarm_config:
                        # For alarm config, keep identifying info
                        if '<Single Name="Name" Type="string">' in line:
                            stable_content.append(line)
                        elif 'CODESYS_HMI' in line:
                            stable_content.append(line)
                
                if stable_content:
                    content = "".join(stable_content).encode("utf-8")
                    return str(zlib.crc32(content) & 0xFFFFFFFF)
                else:
                    # Fallback: if no stable content found, use filename hash
                    import os
                    filename = os.path.basename(file_path)
                    return str(zlib.crc32(filename.encode("utf-8")) & 0xFFFFFFFF)
            
            # Filter out lines that often contain changing timestamps or metadata
            filtered = []
            skip_next = False
            for line in lines:
                if skip_next:
                    skip_next = False
                    continue
                
                # Strip internal CODESYS timestamp
                if 'Name="Timestamp"' in line: continue
                
                # Strip dynamic GUIDs that can change between exports
                # These are internal CODESYS identifiers that don't affect functionality
                if 'Name="Guid"' in line and 'Type="System.Guid"' in line: continue
                
                # For visualization files, also strip object GUIDs that can change
                if line.strip().startswith('<Object Guid="') and ('visu' in line.lower() or 'frame' in line.lower()):
                    continue
                    
                filtered.append(line)
                
            content = "".join(filtered).encode("utf-8")
            return str(zlib.crc32(content) & 0xFFFFFFFF)
        except:
            return ""

    def export(self, obj, context, recursive=None, rel_path=None):
        resolution = context.get("resolution") or {
            "semantic_kind": context.get('effective_type', safe_str(obj.type)),
            "sync_profile": "native_xml"
        }
        if rel_path is None:
            rel_path = build_expected_path(obj, resolution)
        
        # Determine target directory and file path
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        target_dir = os.path.dirname(file_path)
        file_name = os.path.basename(rel_path)
        is_new = not os.path.exists(file_path)
        # --- CACHE SKIP OPTIMIZATION ---
        skip = self._try_cache_skip(obj, rel_path, file_path, context, is_xml=True)
        if skip:
            return skip
        # -------------------------------

        # Get existing file hash before overwriting
        old_hash = "" if is_new else self._hash_file(file_path)
        
        # Export to a temp file first, then compare
        tmp_path = file_path + ".tmp"
        try:
            if recursive is None:
                recursive = get_native_snapshot_recursive(obj, resolution)
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            snapshot_meta = export_native_snapshot(
                obj, tmp_path, projects_obj=resolve_projects(), resolution=resolution, recursive=recursive
            )
            recursive = snapshot_meta.get("recursive")
        except Exception as e:
            log_error("Native export failed for " + obj.get_name() + ": " + safe_str(e))
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except: pass
            return False
            
        if not os.path.exists(tmp_path):
            return False
        
        new_hash = snapshot_meta.get("content_hash") if snapshot_meta else ""
        if not new_hash:
            new_hash = self._hash_file(tmp_path)
        
        # Compare hashes
        if not is_new and old_hash and old_hash == new_hash:
            # Content identical - remove temp, keep original
            try: os.remove(tmp_path)
            except: pass
            if 'exported_paths' in context:
                context['exported_paths'].add(rel_path)
            self._update_cache_entry(obj, rel_path, file_path, context, new_hash)
            return "identical"
        
        # Content changed or new - replace with temp file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            os.rename(tmp_path, file_path)
        except Exception as e:
            log_error("Failed to replace XML file " + file_name + ": " + safe_str(e))
            return False
            
        if 'exported_paths' in context:
            context['exported_paths'].add(rel_path)
        self._update_cache_entry(obj, rel_path, file_path, context, new_hash)
            
        return "new" if is_new else "updated"

    def update(self, obj, file_path, obj_info=None):
        obj_name = obj.get_name() if obj else "Unknown"
        try:
            # Try parent-level import first (more precise)
            try:
                parent = obj.parent
            except:
                parent = None
            
            if parent and hasattr(parent, "import_native"):
                log_info("Updating native object " + obj_name + " via parent import.")
                parent.import_native(file_path)
                return True
            else:
                # Fallback to project-level import (object ref may be stale)
                log_info("Updating native object " + obj_name + " via project import.")
                projects_obj = resolve_projects()
                if projects_obj and projects_obj.primary:
                    projects_obj.primary.import_native(file_path)
                    return True
                return False
        except Exception as e:
            log_error("Native update failed for " + obj_name + ": " + safe_str(e))
            return False

    def create(self, container, name, file_path, type_guid, resolution=None):
        try:
            # CODESYS import_native imports into the project/container
            # If container is provided, use its import_native method
            if container and hasattr(container, "import_native"):
                container.import_native(file_path)
            else:
                # Fallback to project-level import
                projects_obj = resolve_projects()
                if projects_obj and projects_obj.primary:
                    projects_obj.primary.import_native(file_path)
            
            # Find newly created object
            if container:
                for child in container.get_children():
                    if child.get_name().lower() == name.lower():
                        return child
            return None
        except Exception as e:
            log_error("Native import failed for " + name + ": " + safe_str(e))
            return None

class ConfigManager(NativeManager):
    """Specialized handling for configurations (forced XML)"""
    def export(self, obj, context, rel_path=None):
        return super(ConfigManager, self).export(obj, context, rel_path=rel_path)
    
    def create(self, container, name, file_path, type_guid, resolution=None):
        return super(ConfigManager, self).create(container, name, file_path, type_guid, resolution=resolution)

    def update(self, obj, file_path, obj_info):
        return super(ConfigManager, self).update(obj, file_path, obj_info)

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
from codesys_utils import (
    safe_str, clean_filename, calculate_hash, log_info, log_error, log_warning,
    format_st_content, format_property_content, parse_property_content,
    resolve_projects, is_container_device, get_quick_ide_hash, normalize_path
)
from codesys_constants import TYPE_GUIDS, XML_TYPES, EXPORTABLE_TYPES, IMPLEMENTATION_TYPES, XML_TYPES as XML_TYPES_CONST

# --- Helper Functions ---

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
    import tempfile, re
    try:
        projects_obj = resolve_projects()
        if not projects_obj or not projects_obj.primary:
            return False
            
        tmp_path = os.path.join(tempfile.gettempdir(), "nvl_check_%s.xml" % safe_str(obj.guid)[:8])
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        projects_obj.primary.export_native([obj], tmp_path, recursive=False)

        if not os.path.exists(tmp_path):
            return False

        import codecs as _codecs
        with _codecs.open(tmp_path, "r", "utf-8") as xf:
            xml_content = xf.read()
        os.remove(tmp_path)

        # NVL XML contains ListIdentifier and/or NetworkType elements
        if 'ListIdentifier' in xml_content or 'NetworkType' in xml_content:
            return True
        
        return False

    except Exception as e:
        log_warning("Could not check NVL status for " + safe_str(obj.get_name()) + ": " + safe_str(e))
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
            
            parent_type = safe_str(parent.type)
            if stop_at_application and parent_type == TYPE_GUIDS["application"]:
                break
            
            if parent_type in [TYPE_GUIDS["plc_logic"], TYPE_GUIDS["device"]]:
                break
            
            # Skip Task Configuration and individual Tasks in path building
            # Tasks are exported as monolithic Task Configuration XML,
            # so their children should not create Task subfolders on disk
            if parent_type in [TYPE_GUIDS["task_config"], TYPE_GUIDS["task"]]:
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
            curr_type = safe_str(current.type)
            if curr_type == TYPE_GUIDS.get("application"):
                app_name = clean_filename(current.get_name())
            elif curr_type == TYPE_GUIDS.get("device"):
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
            parent_type = safe_str(obj.parent.type)
            if parent_type in [TYPE_GUIDS["pou"], TYPE_GUIDS["itf"]]:
                return obj.parent.get_name()
    except:
        pass
    return None

def build_expected_path(obj, effective_type, is_xml):
    """Build the expected rel_path for an IDE object."""
    from codesys_constants import TYPE_NAMES, TYPE_GUIDS
    
    container = get_container_prefix(obj)
    path_parts = get_object_path(obj)
    obj_name = obj.get_name()
    clean_name = clean_filename(obj_name)

    if is_xml:
        # Special case: POUs exported as XML (graphical) use 'pou_xml' extension
        if effective_type == TYPE_GUIDS["pou"]:
            type_name = "pou_xml"
        else:
            type_name = TYPE_NAMES.get(effective_type, effective_type[:8])
        file_name = clean_name + "." + type_name + ".xml"
    else:
        obj_type = safe_str(obj.type)
        parent_pou = get_parent_pou_name(obj)
        # Nested objects (Action, Method, Property) prefix filename with parent POU name
        if parent_pou and obj_type in [TYPE_GUIDS["action"], TYPE_GUIDS["method"], TYPE_GUIDS["property"], TYPE_GUIDS["itf_method"]]:
            file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
            clean_parent_pou = clean_filename(parent_pou)
            # If the path already has the parent name as a folder, remove it to avoid redundancy
            if path_parts and path_parts[-1] == clean_parent_pou:
                path_parts = path_parts[:-1]
        elif obj_type == TYPE_GUIDS["folder"]:
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
    
    if declaration is None and safe_str(obj.type) == TYPE_GUIDS["itf"]:
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
            if obj_type == TYPE_GUIDS["property_accessor"]:
                if hasattr(obj, "parent") and obj.parent:
                    parent_type = safe_str(obj.parent.type)
                    if parent_type == TYPE_GUIDS["property"]:
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
            if obj_type == TYPE_GUIDS["property"]:
                obj_guid = safe_str(obj.guid)
                try:
                    if obj_guid not in property_accessors:
                        property_accessors[obj_guid] = {
                            'get': None, 'set': None, 'parent_obj': obj
                        }
                    children = obj.get_children()
                    for child in children:
                        child_type = safe_str(child.type)
                        if child_type == TYPE_GUIDS["property_accessor"]:
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
        (effective_type, is_xml, should_skip)
        - effective_type: the resolved type GUID (e.g. NVL replaces GVL)
        - is_xml: True if object should be exported/compared as native XML
        - should_skip: True if object should be ignored (property_accessor, task, etc.)
    """
    obj_type = safe_str(obj.type)
    effective_type = obj_type
    is_xml = False

    # Skip non-exportable
    if obj_type == TYPE_GUIDS["property_accessor"]:
        return obj_type, False, True
    if obj_type == TYPE_GUIDS["task"]:
        return obj_type, False, True
    
    # Hard-exclude devices and modules (feature request: too unstable for XML sync)
    if obj_type in [TYPE_GUIDS.get("device"), TYPE_GUIDS.get("device_module")]:
        return obj_type, False, True

    # Skip all children of monolithic containers - they are exported as
    # recursive XML with their parent. Prevents duplicate export/sync.
    # Logic for devices: Containers (PLCs) are NOT monolithic, so we don't
    # skip their children (Applications and sub-devices).
    monolithic_types = [
        TYPE_GUIDS["alarm_config"], 
        TYPE_GUIDS["visu_manager"],
        TYPE_GUIDS["task_config"],
        TYPE_GUIDS["softmotion_pool"]
    ]
    try:
        parent_type = safe_str(obj.parent.type) if hasattr(obj, 'parent') and obj.parent else ""
        if parent_type in monolithic_types:
            return obj_type, False, True
            
        # Device recursion check:
        # If parent is a device, we only skip if the parent IS a monolithic unit.
        if parent_type == TYPE_GUIDS["device"]:
            if not is_container_device(obj.parent):
                # Parent is functional device (monolithic), so skip children.
                return obj_type, False, True
    except:
        pass

    # Skip per-POU alarm groups/classes — these are auto-generated children of
    # POUs and can't be independently exported. Only alarm groups under the
    # Alarm Configuration tree are valid standalone exports.
    if obj_type in [TYPE_GUIDS["alarm_group"], TYPE_GUIDS["alarm_class"]]:
        try:
            parent_type = safe_str(obj.parent.type)
            if parent_type != TYPE_GUIDS["alarm_config"]:
                return obj_type, False, True
        except:
            pass

    # Skip auto-generated VisualizationStyle objects
    # These are created by CODESYS at multiple locations (Visualization Manager,
    # Application root, project root) and should never be exported/synced.
    if obj_type == TYPE_GUIDS["visu_style"]:
        return obj_type, False, True

    # NVL detection: GVL that is actually a Network Variable List
    if obj_type == TYPE_GUIDS["gvl"]:
        try:
            if is_nvl(obj):
                effective_type = TYPE_GUIDS["nvl_sender"]
                is_xml = True
        except:
            pass

    # Graphical POU detection (LD, CFC, FBD → XML)
    if not is_xml and effective_type in [TYPE_GUIDS["pou"], TYPE_GUIDS["action"], TYPE_GUIDS["method"]]:
        try:
            if is_graphical_pou(obj):
                is_xml = True
        except:
            pass

    # XML_TYPES are always XML
    if effective_type in XML_TYPES:
        is_xml = True

    # Check if type is exportable at all
    if effective_type not in EXPORTABLE_TYPES and effective_type not in XML_TYPES:
        return effective_type, is_xml, True

    return effective_type, is_xml, False

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
            # If q_hash not provided, calculate it based on type
            if q_hash is None:
                q_hash = get_quick_ide_hash(obj, False)
            
            context['new_cache'][norm_path] = {
                "ide_hash": q_hash,
                "disk_mtime": int(s.st_mtime),
                "disk_size": s.st_size
            }
        except: pass

    def export(self, obj, context, rel_path=None):
        """Export object to file system and update metadata"""
        pass
    
    def update(self, obj, file_path, obj_info):
        """Update existing object from file system"""
        pass
    
    def create(self, container, name, file_path, type_guid):
        """Create new object from file system"""
        pass

class FolderManager(ObjectManager):
    """Handle folder creation and management"""
    def export(self, obj, context, rel_path=None):
        if rel_path is None:
            rel_path = build_expected_path(obj, safe_str(obj.type), False)
        
        # Track and cache
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        if 'exported_paths' in context:
            context['exported_paths'].add(rel_path)
        
        # Folders use a constant hash since we just want to track their path/mtime
        self._update_cache_entry(obj, rel_path, file_path, context, q_hash="folder")

        # Skip creating folders for special XML containers
        if safe_str(obj.type) in [TYPE_GUIDS["task_config"], TYPE_GUIDS["alarm_config"]]:
            return "identical"
            
        return "identical"

    def update(self, obj, file_path, obj_info=None):
        # Folders don't have textual content to update
        return False

    def create(self, container, name, file_path, type_guid):
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
        obj_type = safe_str(obj.type)
        obj_name = obj.get_name()
        
        # Build path and filename
        if rel_path is None:
            effective_type = context.get('effective_type', safe_str(obj.type))
            rel_path = build_expected_path(obj, effective_type, False)
        
        # Determine target directory and file path
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        target_dir = os.path.dirname(file_path)
        file_name = os.path.basename(rel_path)
        
        # --- CACHE SKIP OPTIMIZATION ---
        norm_path = normalize_path(rel_path)
        cache = context.get('cache_data')
        if cache:
            # Try to skip slow extraction if IDE and Disk match cache
            q_hash = get_quick_ide_hash(obj, False)
            cached_obj = cache.get('objects', {}).get(norm_path)
            if q_hash and cached_obj and cached_obj.get('ide_hash') == q_hash:
                # IDE matches cache. Now check if Disk matches cache.
                if os.path.exists(file_path):
                    # For performance, we trust mtime/size if available, 
                    # but POUManager usually forces a content check if cache-mismatch.
                    # Here we follow the 'Export' rules: IDE is source of truth.
                    # If IDE matches CACHE, and DISK matches CACHE, then IDE == DISK.
                    s = os.stat(file_path)
                    if int(s.st_mtime) == cached_obj.get('disk_mtime') and s.st_size == cached_obj.get('disk_size'):
                        if 'exported_paths' in context:
                            context['exported_paths'].add(rel_path)
                        self._update_cache_entry(obj, rel_path, file_path, context, q_hash, s)
                        return "identical"
        # -------------------------------

        declaration, implementation = export_object_content(obj)
        # Check if this object type can have implementation even if empty
        obj_type_guid = safe_str(obj.type)
        can_have_impl = obj_type_guid in IMPLEMENTATION_TYPES
        content = format_st_content(declaration, implementation, can_have_impl)
        
        if not content.strip():
            return False
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        
        content_hash = calculate_hash(content)
        is_new = not os.path.exists(file_path)
        
        # Check if content is identical to existing file
        if not is_new:
            try:
                with codecs.open(file_path, "r", "utf-8") as f:
                    existing_content = f.read()
                if calculate_hash(existing_content) == content_hash:
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
        from codesys_utils import parse_st_file
        declaration, implementation = parse_st_file(file_path)
        if declaration is None and implementation is None:
            return False
            
        # We assume the engine already decided we need to update based on content hash
        return update_object_code(obj, declaration, implementation)

    def create(self, container, name, file_path, type_guid):
        from codesys_utils import parse_st_file
        declaration, implementation = parse_st_file(file_path)
        
        obj = None
        try:
            if type_guid == TYPE_GUIDS["gvl"] and hasattr(container, "create_gvl"):
                obj = container.create_gvl(name)
            elif type_guid == TYPE_GUIDS["dut"] and hasattr(container, "create_dut"):
                obj = container.create_dut(name)
            elif type_guid == TYPE_GUIDS["itf"] and hasattr(container, "create_interface"):
                obj = container.create_interface(name)
            elif type_guid == TYPE_GUIDS["method"] and hasattr(container, "create_method"):
                obj = container.create_method(name)
            elif type_guid == TYPE_GUIDS["property"] and hasattr(container, "create_property"):
                obj = container.create_property(name)
            elif type_guid == TYPE_GUIDS["action"] and hasattr(container, "create_action"):
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
                    obj = container.create_child(name, type_guid) if hasattr(container, "create_child") else None
            elif hasattr(container, "create_child"):
                obj = container.create_child(name, type_guid)
                
            if obj:
                update_object_code(obj, declaration, implementation)
                return obj
        except Exception as e:
            log_error("Failed to create " + name + ": " + safe_str(e))
        return None

class PropertyManager(POUManager):
    """Handle properties specifically (combining declaration, Get, and Set)"""
    def export(self, obj, context, rel_path=None):
        obj_guid = safe_str(obj.guid)
        obj_name = obj.get_name()
        
        if obj_guid not in context['property_accessors']:
            prop_data = {'get': None, 'set': None, 'parent_obj': obj}
        else:
            prop_data = context['property_accessors'][obj_guid]
        
        if rel_path is None:
            effective_type = context.get('effective_type', safe_str(obj.type))
            rel_path = build_expected_path(obj, effective_type, False)
        
        # Determine target directory and file path
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        target_dir = os.path.dirname(file_path)
        file_name = os.path.basename(rel_path)
        
        # --- CACHE SKIP OPTIMIZATION ---
        norm_path = normalize_path(rel_path)
        cache = context.get('cache_data')
        if cache:
            # Properties are special: q_hash handles decl + kids
            q_hash = get_quick_ide_hash(obj, False)
            cached_obj = cache.get('objects', {}).get(norm_path)
            if q_hash and cached_obj and cached_obj.get('ide_hash') == q_hash:
                if os.path.exists(file_path):
                    s = os.stat(file_path)
                    if int(s.st_mtime) == cached_obj.get('disk_mtime') and s.st_size == cached_obj.get('disk_size'):
                        if 'exported_paths' in context:
                            context['exported_paths'].add(rel_path)
                        self._update_cache_entry(obj, rel_path, file_path, context, q_hash, s)
                        return "identical"
        # -------------------------------

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
        content_hash = calculate_hash(combined_content)
        
        is_new = not os.path.exists(file_path)
        
        # Check if content is identical to existing file
        if not is_new:
            try:
                with codecs.open(file_path, "r", "utf-8") as f:
                    existing_content = f.read()
                if calculate_hash(existing_content) == content_hash:
                    if 'exported_paths' in context:
                        context['exported_paths'].add(rel_path)
                    
                    self._update_cache_entry(obj, rel_path, file_path, context, content_hash)
                    return "identical"
            except:
                pass
        
        try:
            with codecs.open(file_path, "w", "utf-8") as f:
                f.write(combined_content)
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
                content = f.read()
        except: return False
        
        declaration, get_impl_combined, set_impl_combined = parse_property_content(content)
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
        
        return updated

    def create(self, container, name, file_path, type_guid):
        try:
            with codecs.open(file_path, "r", "utf-8") as f:
                content = f.read()
        except: return None
        
        declaration, get_impl_combined, set_impl_combined = parse_property_content(content)
        
        obj = None
        try:
            if hasattr(container, "create_property"):
                obj = container.create_property(name)
            elif hasattr(container, "create_child"):
                obj = container.create_child(name, type_guid)
                
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

    def export(self, obj, context, recursive=False, rel_path=None):
        if rel_path is None:
            effective_type = context.get('effective_type', safe_str(obj.type))
            rel_path = build_expected_path(obj, effective_type, True)
        
        # Determine target directory and file path
        file_path = os.path.join(context['export_dir'], rel_path.replace("/", os.sep))
        target_dir = os.path.dirname(file_path)
        file_name = os.path.basename(rel_path)
        is_new = not os.path.exists(file_path)
        # --- CACHE SKIP OPTIMIZATION ---
        norm_path = normalize_path(rel_path)
        cache = context.get('cache_data')
        if cache:
            # For XML, get_quick_ide_hash returns the stable content hash
            q_hash = get_quick_ide_hash(obj, True)
            cached_obj = cache.get('objects', {}).get(norm_path)
            if q_hash and cached_obj and cached_obj.get('ide_hash') == q_hash:
                if os.path.exists(file_path):
                    s = os.stat(file_path)
                    if int(s.st_mtime) == cached_obj.get('disk_mtime') and s.st_size == cached_obj.get('disk_size'):
                        if 'exported_paths' in context:
                            context['exported_paths'].add(rel_path)
                        self._update_cache_entry(obj, rel_path, file_path, context, q_hash, s)
                        return "identical"
        # -------------------------------

        # Get existing file hash before overwriting
        old_hash = "" if is_new else self._hash_file(file_path)
        
        # Export to a temp file first, then compare
        tmp_path = file_path + ".tmp"
        try:
            projects_obj = resolve_projects()
            if projects_obj and projects_obj.primary:
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)
                projects_obj.primary.export_native([obj], tmp_path, recursive=recursive)
            else:
                log_error("Native export failed: 'projects' object not found or no primary project.")
                return False
        except Exception as e:
            log_error("Native export failed for " + obj.get_name() + ": " + safe_str(e))
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except: pass
            return False
            
        if not os.path.exists(tmp_path):
            return False
        
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

    def create(self, container, name, file_path, type_guid):
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
        # Devices are monolithic only if they are not containers (Project Roots)
        recursive = True
        if safe_str(obj.type) == TYPE_GUIDS["device"]:
            if is_container_device(obj):
                recursive = False
        
        return super(ConfigManager, self).export(obj, context, recursive=recursive, rel_path=rel_path)
    
    def create(self, container, name, file_path, type_guid):
        return super(ConfigManager, self).create(container, name, file_path, type_guid)

    def update(self, obj, file_path, obj_info):
        return super(ConfigManager, self).update(obj, file_path, obj_info)

# -*- coding: utf-8 -*-
"""
codesys_managers.py - Object Manager classes for CODESYS synchronization

Extracts object-specific logic for export and import operations.
"""
import os
import codecs
import time
from codesys_utils import (
    safe_str, clean_filename, calculate_hash, log_info, log_error, log_warning,
    format_st_content, format_property_content, parse_property_content,
    resolve_projects
)
from codesys_constants import TYPE_GUIDS, XML_TYPES, EXPORTABLE_TYPES, XML_TYPES as XML_TYPES_CONST

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
            
            parent_name = clean_filename(parent.get_name())
            path_parts.insert(0, parent_name)
            current = parent
        except:
            break
    return path_parts

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

def export_object_content(obj):
    """Extract declaration and implementation text from object."""
    declaration = None
    implementation = None
    try:
        if hasattr(obj, "has_textual_declaration") and obj.has_textual_declaration:
            declaration = obj.textual_declaration.text
    except: pass
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
                    children = obj.get_children()
                    for child in children:
                        child_type = safe_str(child.type)
                        if child_type == TYPE_GUIDS["property_accessor"]:
                            if obj_guid not in property_accessors:
                                property_accessors[obj_guid] = {
                                    'get': None, 'set': None, 'parent_obj': obj
                                }
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

# --- Manager Classes ---

class ObjectManager(object):
    """Base class for managing CODESYS objects"""
    def export(self, obj, context):
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
    def export(self, obj, context):
        path_parts = get_object_path(obj)
        clean_name = clean_filename(obj.get_name())
        path_parts.append(clean_name)
        
        target_dir = os.path.join(context['src_dir'], *path_parts)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            print("Created folder: src/" + "/".join(path_parts))
            
        rel_path = "src/" + "/".join(path_parts)
        context['metadata']['objects'][rel_path] = {
            "guid": safe_str(obj.guid),
            "type": safe_str(obj.type),
            "name": obj.get_name(),
            "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else None,
            "content_hash": ""
        }
        return True

    def update(self, obj, file_path, obj_info):
        # Folders don't have textual content to update
        obj_info["last_modified"] = safe_str(os.path.getmtime(file_path))
        return False

    def create(self, container, name, file_path, type_guid):
        # For folders, container should be the parent folder/application
        # But we also have absolute path in file_path (which is relative in metadata)
        from codesys_utils import ensure_folder_path
        try:
            # In CODESYS, 'projects' is an environment global, no need to import it
            # file_path in this context is the rel_path from metadata e.g. "src/Folder/Sub"
            return ensure_folder_path(file_path, projects.primary)
        except:
            return None

class POUManager(ObjectManager):
    """Handle standard textual objects (POUs, GVLs, DUTs)"""
    def export(self, obj, context):
        obj_type = safe_str(obj.type)
        obj_name = obj.get_name()
        
        # Build path and filename
        path_parts = get_object_path(obj)
        clean_name = clean_filename(obj_name)
        
        parent_pou = get_parent_pou_name(obj)
        if parent_pou and obj_type in [TYPE_GUIDS["action"], TYPE_GUIDS["method"]]:
            file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
            if path_parts and path_parts[-1] == clean_filename(parent_pou):
                path_parts = path_parts[:-1]
        else:
            file_name = clean_name + ".st"
            
        target_dir = os.path.join(context['src_dir'], *path_parts) if path_parts else context['src_dir']
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        file_path = os.path.join(target_dir, file_name)
        
        declaration, implementation = export_object_content(obj)
        content = format_st_content(declaration, implementation)
        
        if not content.strip():
            return False
            
        content_normalized = content.replace('\r\n', '\n').replace('\r', '\n')
        with open(file_path, "wb") as f:
            f.write(content_normalized.encode('utf-8'))
            
        rel_path = "/".join(["src"] + path_parts + [file_name])
        context['metadata']['objects'][rel_path] = {
            "guid": safe_str(obj.guid),
            "type": obj_type,
            "name": obj_name,
            "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else None,
            "content_hash": calculate_hash(content),
            "last_modified": safe_str(os.path.getmtime(file_path))
        }
        return True

    def update(self, obj, file_path, obj_info):
        from codesys_utils import parse_st_file
        declaration, implementation = parse_st_file(file_path)
        if declaration is None and implementation is None:
            return False
            
        full_content = format_st_content(declaration, implementation)
        current_hash = calculate_hash(full_content)
        
        if current_hash == obj_info.get("content_hash"):
            # Update timestamp in metadata but no need to update object
            obj_info["last_modified"] = safe_str(os.path.getmtime(file_path))
            return False
            
        if update_object_code(obj, declaration, implementation):
            obj_info["content_hash"] = current_hash
            obj_info["last_modified"] = safe_str(os.path.getmtime(file_path))
            return True
        return False

    def create(self, container, name, file_path, type_guid):
        from codesys_utils import parse_st_file
        declaration, implementation = parse_st_file(file_path)
        
        obj = None
        try:
            if type_guid == TYPE_GUIDS["gvl"] and hasattr(container, "create_gvl"):
                obj = container.create_gvl(name)
            elif type_guid == TYPE_GUIDS["dut"] and hasattr(container, "create_dut"):
                obj = container.create_dut(name)
            elif type_guid == TYPE_GUIDS["method"] and hasattr(container, "create_method"):
                obj = container.create_method(name)
            elif type_guid == TYPE_GUIDS["property"] and hasattr(container, "create_property"):
                obj = container.create_property(name)
            elif type_guid == TYPE_GUIDS["action"] and hasattr(container, "create_action"):
                obj = container.create_action(name)
            elif hasattr(container, "create_pou"):
                # Default to Program for general POU creation
                try:
                    from ScriptEngine import PouType
                    p_type = PouType.Program
                except:
                    p_type = 0 # Fallback for some environments
                obj = container.create_pou(name, p_type)
            elif hasattr(container, "create_child"):
                obj = container.create_child(name, type_guid)
                
            if obj:
                update_object_code(obj, declaration, implementation)
                return obj
        except Exception as e:
            log_error("Failed to create " + name + ": " + safe_str(e))
        return None

class PropertyManager(ObjectManager):
    """Handle properties with GET/SET accessors"""
    def export(self, obj, context):
        obj_guid = safe_str(obj.guid)
        obj_name = obj.get_name()
        
        # Get accessors from property_accessors map (passed in context)
        prop_data = context.get('property_accessors', {}).get(obj_guid)
        if not prop_data:
            return False
            
        path_parts = get_object_path(obj)
        clean_name = clean_filename(obj_name)
        
        parent_pou = get_parent_pou_name(obj)
        if parent_pou:
            file_name = clean_filename(parent_pou) + "." + clean_name + ".st"
            if path_parts and path_parts[-1] == clean_filename(parent_pou):
                path_parts = path_parts[:-1]
        else:
            file_name = clean_name + ".st"
            
        target_dir = os.path.join(context['src_dir'], *path_parts) if path_parts else context['src_dir']
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        file_path = os.path.join(target_dir, file_name)
        
        declaration, _ = export_object_content(obj)
        get_impl = None
        if prop_data['get']:
            g_decl, g_impl = export_object_content(prop_data['get'])
            get_impl = format_st_content(g_decl, g_impl)
            
        set_impl = None
        if prop_data['set']:
            s_decl, s_impl = export_object_content(prop_data['set'])
            set_impl = format_st_content(s_decl, s_impl)
            
        content = format_property_content(declaration, get_impl, set_impl)
        if not content.strip():
            return False
            
        content_normalized = content.replace('\r\n', '\n').replace('\r', '\n')
        with open(file_path, "wb") as f:
            f.write(content_normalized.encode('utf-8'))
            
        rel_path = "/".join(["src"] + path_parts + [file_name])
        context['metadata']['objects'][rel_path] = {
            "guid": obj_guid,
            "type": safe_str(obj.type),
            "name": obj_name,
            "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else None,
            "content_hash": calculate_hash(content),
            "last_modified": safe_str(os.path.getmtime(file_path))
        }
        return True

    def update(self, obj, file_path, obj_info):
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
        
        if updated:
            obj_info["content_hash"] = calculate_hash(content)
            obj_info["last_modified"] = safe_str(os.path.getmtime(file_path))
            
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
    def export(self, obj, context):
        obj_name = obj.get_name()
        path_parts = get_object_path(obj)
        clean_name = clean_filename(obj_name)
        file_name = clean_name + ".xml"
        
        target_dir = os.path.join(context['xml_dir'], *path_parts) if path_parts else context['xml_dir']
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        file_path = os.path.join(target_dir, file_name)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            
        try:
            # Resolve 'projects' object (available as a global in CODESYS)
            projects_obj = resolve_projects()
            if projects_obj and projects_obj.primary:
                projects_obj.primary.export_native([obj], file_path, recursive=True)
            else:
                log_error("Native export failed: 'projects' object not found or no primary project.")
                return False
        except Exception as e:
            log_error("Native export failed for " + obj_name + ": " + safe_str(e))
            return False
            
        if not os.path.exists(file_path):
            return False
            
        rel_path = "/".join(["xml"] + path_parts + [file_name])
        context['metadata']['objects'][rel_path] = {
            "guid": safe_str(obj.guid),
            "type": safe_str(obj.type),
            "name": obj_name,
            "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else None,
            "content_hash": "",
            "last_modified": safe_str(os.path.getmtime(file_path))
        }
        return True

    def create(self, container, name, file_path, type_guid):
        try:
            # CODESYS import_native imports into the project/container
            # 'projects' is a global object
            projects.primary.import_native(file_path, filter=None)
            
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
    def export(self, obj, context):
        # Override target dir to config_dir
        path_parts = get_object_path(obj)
        clean_name = clean_filename(obj.get_name())
        file_name = clean_name + ".xml"
        
        target_dir = os.path.join(context['config_dir'], *path_parts) if path_parts else context['config_dir']
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        file_path = os.path.join(target_dir, file_name)
        
        try:
            # projects is a global object
            projects.primary.export_native([obj], file_path, recursive=True)
        except: return False
        
        rel_path = "/".join(["config"] + path_parts + [file_name])
        context['metadata']['objects'][rel_path] = {
            "guid": safe_str(obj.guid),
            "type": safe_str(obj.type),
            "name": obj.get_name(),
            "parent": safe_str(obj.parent.get_name()) if obj.parent and hasattr(obj.parent, 'get_name') else None,
            "content_hash": "",
            "last_modified": safe_str(os.path.getmtime(file_path))
        }
        return True
    
    def create(self, container, name, file_path, type_guid):
        return super(ConfigManager, self).create(container, name, file_path, type_guid)

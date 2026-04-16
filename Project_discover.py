# -*- coding: utf-8 -*-
"""
Project_discover.py - Cleanly output the project object tree.

Uses get_children(recursive=True) for reliable enumeration,
then reconstructs the tree structure from parent references.
"""
import os

from Project_bootstrap import clear_hidden_modules, load_hidden_modules

# Force reload of shared modules to pick up latest changes
clear_hidden_modules()
load_hidden_modules([
    "codesys_constants",
    "codesys_utils",
    "codesys_managers",
    "codesys_type_profiles",
    "codesys_type_system",
], script_file=__file__)

# Import shared constants and utilities
from codesys_constants import TYPE_GUIDS
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_warning, log_error,
    resolve_projects, get_project_prop, get_detected_codesys_version
)
from codesys_managers import is_nvl
from codesys_type_profiles import PROJECT_PROPERTY_KEY, get_profile_label
from codesys_type_system import resolve_runtime_object, get_selected_profile_name

# Reverse mapping of TYPE_GUIDS kept only as a compatibility label fallback.
TYPE_NAMES = {v: k for k, v in TYPE_GUIDS.items()}

def discover_project():
    """Discover and log all project objects as a tree."""
    base_dir, error = load_base_dir()
    if error:
        base_dir = os.getcwd()
    
    init_logging(base_dir)
    
    try:
        projects_obj = resolve_projects()
        if not projects_obj or not projects_obj.primary:
            log_error("No primary project open!")
            print("Error: No primary project open in CODESYS!")
            return

        proj = projects_obj.primary
        
        # Use recursive=True for reliable enumeration (same approach as export)
        all_objects = proj.get_children(recursive=True)
        
        profile_name = get_selected_profile_name(project_profile=get_project_prop(PROJECT_PROPERTY_KEY))
        detected_version = get_detected_codesys_version()
        profile_label = get_profile_label(profile_name)
        print("\n=== CODESYS Project Tree (" + str(len(all_objects)) + " objects) ===")
        print("Detected CODESYS version: " + safe_str(detected_version))
        print("Selected type profile: " + profile_name + " (" + safe_str(profile_label) + ")\n")
        
        # Build a set of all known GUIDs
        known_guids = set()
        for obj in all_objects:
            try:
                known_guids.add(safe_str(obj.guid))
            except:
                pass
        
        # Build parent -> children map using GUIDs
        children_map = {}   # parent_guid -> [child objects]
        root_children = []  # objects whose parent is NOT in the recursive list (i.e. project root)
        
        for obj in all_objects:
            try:
                parent_guid = None
                try:
                    if hasattr(obj, "parent") and obj.parent:
                        parent_guid = safe_str(obj.parent.guid)
                except:
                    pass
                
                if parent_guid and parent_guid in known_guids:
                    # Parent is another discovered object
                    if parent_guid not in children_map:
                        children_map[parent_guid] = []
                    children_map[parent_guid].append(obj)
                else:
                    # Parent is the project root (not in recursive list)
                    root_children.append(obj)
            except:
                pass
        
        # Recursive tree print
        tree_lines = []
        unknown_types = {} # guid -> example_name
        
        def print_node(obj, level):
            try:
                obj_name = safe_str(obj.get_name())
                obj_type_guid = safe_str(obj.type)
                obj_class = obj.__class__.__name__

                resolution = resolve_runtime_object(obj, profile_name)
                obj_type_name = resolution.get("semantic_kind")
                sync_profile = resolution.get("sync_profile") or ""
                evidence = resolution.get("evidence") or []
                is_unknown = not obj_type_name
                if not obj_type_name:
                    obj_type_name = TYPE_NAMES.get(obj_type_guid, "UNKNOWN_%s" % obj_type_guid[:8])
                
                # Special case: GVLs that are actually NVLs
                if obj_type_guid == TYPE_GUIDS["gvl"]:
                    try:
                        if is_nvl(obj):
                            obj_type_name = "nvl"
                    except:
                        pass
                
                prefix = "[!] " if is_unknown else ""
                if is_unknown:
                    unknown_types[obj_type_guid] = obj_name

                parts = [obj_type_name, obj_type_guid]
                if sync_profile:
                    parts.append(sync_profile)
                parts.append(obj_class)
                line = "  " * level + "|-- " + prefix + obj_name + " (" + " | ".join(parts) + ")"
                print(line)
                tree_lines.append(line)

                if evidence:
                    evidence_line = "  " * (level + 1) + "evidence: " + ", ".join([safe_str(item) for item in evidence])
                    print(evidence_line)
                    tree_lines.append(evidence_line)
                
                # Print children from our map
                obj_guid = safe_str(obj.guid)
                for child in children_map.get(obj_guid, []):
                    print_node(child, level + 1)
            except:
                pass
        
        for obj in root_children:
            print_node(obj, 0)
        
        # Log everything as ONE block
        if tree_lines:
            log_info("PROJECT TREE:\n" + "\n".join(tree_lines))
        else:
            log_error("No tree nodes were generated. root_children=" + str(len(root_children)) + " all_objects=" + str(len(all_objects)))
        
        # Summary of unknown types
        if unknown_types:
            print("\n!!! UNKNOWN OBJECT TYPES FOUND !!!")
            print("These GUIDs are unresolved for the selected type profile:")
            for guid, name in unknown_types.items():
                line = " - %s (Example: %s)" % (guid, name)
                print(line)
                log_warning("Unknown object type found: " + line)
            print("Consider updating the selected profile or adding a new alias/context rule.\n")

        print("\n=== Discovery Complete (" + str(len(tree_lines)) + " nodes). Tree stored in sync_debug.log ===")

    except Exception as e:
        log_error("Critical error during discovery: " + safe_str(e))
        print("Critical error: " + safe_str(e))

if __name__ == "__main__":
    discover_project()

# -*- coding: utf-8 -*-
"""
Project_discover.py - Cleanly output the project object tree.

Uses get_children(recursive=True) for reliable enumeration,
then reconstructs the tree structure from parent references.
"""
import os
import sys

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

# Import shared constants and utilities
from codesys_constants import TYPE_GUIDS
from codesys_utils import (
    safe_str, load_base_dir, init_logging, log_info, log_warning, log_error,
    resolve_projects
)
from codesys_managers import is_nvl

# Reverse mapping of TYPE_GUIDS for logging human-readable type names
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
        
        print("\n=== CODESYS Project Tree (" + str(len(all_objects)) + " objects) ===\n")
        
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
                
                is_unknown = obj_type_guid not in TYPE_NAMES
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

                line = "  " * level + "|-- " + prefix + obj_name + " (" + obj_type_name + " | " + obj_type_guid + " | " + obj_class + ")"
                print(line)
                tree_lines.append(line)
                
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
            print("These GUIDs are missing from codesys_constants.py:")
            for guid, name in unknown_types.items():
                line = " - %s (Example: %s)" % (guid, name)
                print(line)
                log_warning("Unknown object type found: " + line)
            print("Please add them to TYPE_GUIDS in codesys_constants.py\n")

        print("\n=== Discovery Complete (" + str(len(tree_lines)) + " nodes). Tree stored in sync_debug.log ===")

    except Exception as e:
        log_error("Critical error during discovery: " + safe_str(e))
        print("Critical error: " + safe_str(e))

if __name__ == "__main__":
    discover_project()

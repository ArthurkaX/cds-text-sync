import os
import sys
import time
import codecs
import json

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]
from codesys_constants import (
    IMPL_MARKER, TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, FORBIDDEN_CHARS
)
from codesys_utils import (
    safe_str, clean_filename, load_base_dir,
    save_metadata, calculate_hash, format_st_content,
    log_info, log_warning, log_error, MetadataLock,
    init_logging, backup_project_binary, format_property_content,
    resolve_projects, update_application_count_flag, ensure_git_configs
)
from codesys_managers import (
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    get_object_path, collect_property_accessors, is_nvl, is_graphical_pou
)

# Shared constants and utilities imported from modules


def cleanup_orphaned_files(export_dir, current_objects, silent=False):
    """
    Find and optionally delete files in export_dir that are not in current_objects.
    """
    orphaned_items = []
    
    # We'll collect everything first to show a preview
    for root, dirs, files in os.walk(export_dir):
        # Calculate relative path from export_dir
        rel_root = os.path.relpath(root, export_dir)
        if rel_root == ".":
            rel_root = ""
            
        # Check files
        for f in files:
            # Skip reserved files and folders
            if f in ["_metadata.json", "_config.json", "_metadata.csv", "BASE_DIR", "sync_debug.log", ".project", ".gitattributes", ".gitignore"] or f.startswith("."):
                continue
            
            # Skip project folder if it exists (for Git LFS)
            if rel_root.startswith("project") or rel_root == "project":
                continue

            # Only consider our export types to be safe
            if not (f.endswith(".st") or f.endswith(".xml")):
                continue
                
            rel_path = os.path.join(rel_root, f).replace("\\", "/")
            if rel_path not in current_objects:
                orphaned_items.append(rel_path)

    if not orphaned_items:
        return True

    # Check for auto-delete property
    try:
        from codesys_utils import get_project_prop
        auto_delete = get_project_prop("cds-sync-auto-delete-orphans", False)
    except:
        auto_delete = False

    if silent:
        if auto_delete:
            result = (0,) # Simulate Delete
        else:
             print("Silent Mode: " + str(len(orphaned_items)) + " orphans ignored (set cds-sync-auto-delete-orphans=True to delete).")
             return True # Ignore
    else:
        # Prompt user
        message = "The following files exist in the export directory but are NOT in the CODESYS project (orphans):\n\n"
        # Show first 15 files as preview
        for item in orphaned_items[:15]:
            message += "- " + item + "\n"
        if len(orphaned_items) > 15:
            message += "... and " + str(len(orphaned_items) - 15) + " more.\n"
        
        message += "\nWould you like to delete these orphaned files?"
        
        # buttons: Delete, Ignore, Cancel
        try:
            result = system.ui.choose(message, ("Delete Orphans", "Ignore", "Cancel Export"))
        except:
            # Fallback for environments where choose is not available or fails
            print("UI Choose not available, skipping cleanup.")
            return True
    
    if result[0] == 0: # Delete
        print("Cleaning up orphaned files...")
        for rel_path in orphaned_items:
            full_path = os.path.join(export_dir, rel_path.replace("/", os.sep))
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    print("Deleted: " + rel_path)
            except Exception as e:
                print("Error deleting " + rel_path + ": " + safe_str(e))
        
        # Now clean up empty directories
        # Use topdown=False to delete subdirectories before parents
        for root, dirs, files in os.walk(export_dir, topdown=False):
            rel_root = os.path.relpath(root, export_dir)
            if rel_root == "." or not rel_root:
                continue
            
            rel_path = rel_root.replace("\\", "/")
            
            # Check if this folder or any of its children should exist
            folder_needed = False
            for obj_path in current_objects:
                if obj_path.startswith(rel_path + "/"):
                    folder_needed = True
                    break
            
            if not folder_needed and rel_path not in current_objects:
                # If directory is empty, delete it
                try:
                    if not os.listdir(root):
                        os.rmdir(root)
                        print("Deleted empty folder: " + rel_path)
                except:
                    pass
        return True
    elif result[0] == 1: # Ignore
        print("Orphaned files ignored.")
        return True
    else: # Cancel
        print("Export cancelled during cleanup.")
        return False





def export_project(export_dir, projects_obj=None, silent=False):
    """Export all project objects to folder structure with metadata"""
    
    # Resolving projects object
    projects_obj = resolve_projects(projects_obj, globals())
    
    if projects_obj is None or not projects_obj.primary:
        msg = "Error: 'projects' object not found or no project open."
        if not silent:
            system.ui.error(msg)
        else:
            print(msg)
        return
    
    # Create export directory
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)
    
    # Ensure Git config files exist
    ensure_git_configs(export_dir)
    
    # Create project binary backup (moved down)
    
    print("=== Starting Project Export ===")
    update_application_count_flag()
    start_time = time.time()
    print("Export directory: " + export_dir)
    
    # Metadata structure
    current_project_name = safe_str(projects_obj.primary)
    metadata = {
        "project_name": current_project_name,
        "export_timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "export_xml": False,
        "objects": {}
    }
    
    try:
        if hasattr(projects_obj.primary, "path"):
            metadata["project_path"] = safe_str(projects_obj.primary.path)
    except:
        pass
    
    # Read settings from project properties (Source of Truth)
    from codesys_utils import get_project_prop
    metadata["export_xml"] = get_project_prop("cds-sync-export-xml", False)
    backup_binary = get_project_prop("cds-sync-backup-binary", False)
    
    # Store settings in metadata for reference
    metadata["settings"] = {
        "export_xml": metadata["export_xml"],
        "backup_binary": backup_binary
    }
    
    # Check if metadata already exists with different project
    metadata_path = os.path.join(export_dir, "_metadata.json")
    if os.path.exists(metadata_path):
        try:
            with codecs.open(metadata_path, "r", "utf-8") as f:
                existing_metadata = json.load(f)
            
            # Note: We now prioritize project properties over file metadata
            # Only preserve settings if they're not in project properties

            existing_project = existing_metadata.get("project_name", "")
            if existing_project and existing_project != current_project_name:
                if silent:
                     print("Warning: Exporting to folder owned by different project: " + existing_project)
                else:
                    message = "WARNING: This directory contains exports from a different project!\n\n"
                    message += "Current project: " + current_project_name + "\n"
                    message += "Existing exports: " + existing_project + "\n\n"
                    message += "Exporting will OVERWRITE the existing files.\n\n"
                    message += "Are you sure you want to proceed?"
                    
                    result = system.ui.choose(message, ("Yes, Overwrite", "No, Cancel"))
                    
                    if result[0] != 0:
                        print("Export cancelled by user - project mismatch")
                        return
        except:
            # If we can't read existing metadata, continue with export
            pass
    
    # Execute binary backup if enabled
    if backup_binary:
        print("Binary backup enabled.")
        backup_project_binary(export_dir, projects_obj)
    else:
        print("Binary backup disabled (skipping .project copy).")

    # Get all objects recursively
    all_objects = projects_obj.primary.get_children(recursive=True)
    print("Found " + str(len(all_objects)) + " total objects")
    
    exported_new = 0
    exported_updated = 0
    exported_identical = 0
    skipped_count = 0
    
    # Phase 6: Metadata migration / detection
    existing_objects = metadata.get("objects", {})
    has_old_format = any(k.startswith(("src/", "xml/", "config/")) for k in existing_objects)
    
    if has_old_format:
        print("Legacy directory structure (src/xml/config) detected.")
        print("Migrating to hierarchical Device/Application folders...")
        log_warning("Legacy project structure detected. Metadata will be reset for re-export.")
        # Clear objects map to ensure clean metadata and trigger orphan cleanup for old dirs
        metadata["objects"] = {}
    
    # Collect all property accessors
    property_accessors = collect_property_accessors(all_objects)
    print("Found " + str(len(property_accessors)) + " properties with accessors")
    
    # Initialize managers
    managers = {
        TYPE_GUIDS["folder"]: FolderManager(),
        TYPE_GUIDS["property"]: PropertyManager(),
        TYPE_GUIDS["task_config"]: ConfigManager(),
        # Default for textual objects
        "default": POUManager(),
        "native": NativeManager()
    }
    
    context = {
        'export_dir': export_dir,
        'metadata': metadata,
        'property_accessors': property_accessors
    }

    # Second pass: export all objects
    for obj in all_objects:
        try:
            # Validate that object has required methods
            if not hasattr(obj, 'type') or not hasattr(obj, 'get_name') or not hasattr(obj, 'guid'):
                continue
                
            obj_type = safe_str(obj.type)
            
            # Skip property accessors - they will be handled with their parent property
            if obj_type == TYPE_GUIDS["property_accessor"]:
                continue
            
            # Select manager
            effective_type = obj_type
            use_native = False
            
            # Skip ALL individual Task objects - they are handled by Task Configuration XML
            if obj_type == TYPE_GUIDS["task"]:
                # Individual tasks don't need independent export
                continue
            
            # Special case: GVLs that are actually NVLs should be treated as native XML
            if obj_type == TYPE_GUIDS["gvl"]:
                try:
                    if is_nvl(obj):
                        effective_type = TYPE_GUIDS["nvl_sender"]
                        log_info("Detected NVL: " + safe_str(obj.get_name()) + " -> switching to XML export")
                except:
                    pass

            # Special case: POUs/actions/methods with graphical implementation (LD, CFC, FBD)
            # must be exported as native XML.
            if effective_type in [TYPE_GUIDS["pou"], TYPE_GUIDS["action"], TYPE_GUIDS["method"]]:
                try:
                    if is_graphical_pou(obj):
                        use_native = True
                        log_info("Detected graphical object: " + safe_str(obj.get_name()) + " -> switching to XML export")
                except:
                    pass
                
            if use_native:
                manager = managers["native"]
            elif effective_type in managers:
                manager = managers[effective_type]
            elif effective_type in XML_TYPES:
                if not metadata.get("export_xml", False) and effective_type not in [TYPE_GUIDS["task_config"], TYPE_GUIDS["nvl_sender"], TYPE_GUIDS["nvl_receiver"]]:
                    continue
                manager = managers["native"]
            elif effective_type in EXPORTABLE_TYPES:
                manager = managers["default"]
            else:
                continue
                
            context['effective_type'] = effective_type
            result = manager.export(obj, context)
            if result == "new":
                exported_new += 1
            elif result == "updated":
                exported_updated += 1
            elif result == "identical":
                exported_identical += 1
            else:
                # False/None = skipped (no content, error, etc.)
                pass
            
        except Exception as e:
            log_error("Error exporting " + safe_str(obj) + ": " + safe_str(e))
    
    # Phase 7: Cleanup empty folders from metadata
    # (A folder is only kept if it contains at least one exportable file)
    all_paths_list = list(metadata["objects"].keys())
    needed_folders = set()
    for p in all_paths_list:
        if metadata["objects"][p].get("type") != TYPE_GUIDS["folder"]:
            # This is a file, mark all its parent paths as needed
            parts = p.split("/")
            for i in range(1, len(parts)):
                needed_folders.add("/".join(parts[:i]))
    
    # Filter metadata to only include files and needed folders
    metadata["objects"] = {p: info for p, info in metadata["objects"].items() 
                           if info.get("type") != TYPE_GUIDS["folder"] or p in needed_folders}

    # Cleanup orphaned files (files on disk not in current export)
    if not cleanup_orphaned_files(export_dir, metadata["objects"], silent=silent):
        return
    
    # Debug: Count methods in metadata before saving
    method_count = sum(1 for info in metadata["objects"].values() if info.get("type") == TYPE_GUIDS["method"])
    exported_total = exported_new + exported_updated + exported_identical
    print("DEBUG: Before saving - Total objects: " + str(len(metadata["objects"])) + ", Methods: " + str(method_count))
    
    # Write metadata file with consistent field order (60s timeout for large projects)
    with MetadataLock(export_dir, timeout=60):
        if save_metadata(export_dir, metadata):
            print("Created: _config.json and _metadata.csv")
        else:
            print("Error writing metadata")
            
    
    print("=== Export Complete ===")
    elapsed_time = time.time() - start_time
    print("New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical))
    print("Skipped: " + str(skipped_count) + " objects (no textual content)")
    print("Time elapsed: {:.2f} seconds".format(elapsed_time))
    print("Completed at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    
    summary = "Exported: " + str(exported_total) + " (New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical) + ")"
    log_info("Export complete! " + summary)
    
    # Show completion notification
    if silent:
        try:
            from codesys_ui import show_toast
            show_toast("Export Complete", summary + "\nTime: {:.2f}s".format(elapsed_time))
        except:
            print("Export complete (toast unavailable)")
    else:
        # Interactive mode: check if user prefers toast over modal dialog
        silent_mode = get_project_prop("cds-sync-silent-mode", False)
        if silent_mode:
            try:
                from codesys_ui import show_toast
                show_toast("Export Complete", summary + "\nTime: {:.2f}s".format(elapsed_time))
            except:
                print("Export complete (Silent mode active, but UI module failed)")
        else:
            system.ui.info("Export complete!\n\n" + summary + "\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))


def main():
    base_dir, error = load_base_dir()
    if error:
        system.ui.warning(error)
        return
        
    # Check if we are being run in silent mode (e.g. from Daemon)
    is_silent = globals().get("SILENT", False)
    
    init_logging(base_dir)
    export_project(base_dir, silent=is_silent)


if __name__ == "__main__":
    main()
import os
import time
from codesys_constants import (
    IMPL_MARKER, TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, FORBIDDEN_CHARS
)
from codesys_utils import (
    safe_str, clean_filename, load_base_dir,
    save_metadata, calculate_hash, format_st_content,
    log_info, log_warning, log_error, MetadataLock,
    save_libraries, extract_libraries_from_project,
    init_logging, backup_project_binary, format_property_content,
    resolve_projects
)
from codesys_managers import (
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    get_object_path, collect_property_accessors
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


def ensure_git_configs(export_dir):
    """Create .gitignore and .gitattributes if they don't exist."""
    gitignore_path = os.path.join(export_dir, ".gitignore")
    gitattributes_path = os.path.join(export_dir, ".gitattributes")
    
    # Gitignore handling
    if not os.path.exists(gitignore_path):
        content = [
            "# CODESYS Sync local files",
            "_config.json",
            "_metadata.csv",
            "*.log",
            "*.tmp",
            "*.bak",
            "",
            "# CODESYS temporary and build files",
            "*.~u",
            "*.precompilecache",
            "*.opt",
            "*.bootinfo",
            "*.bootinfo_guids",
            "*.compileinfo",
            "*.simulation.bootinfo",
            "*.simulation.bootinfo_guids",
            "*.simulation.compileinfo",
            ""
        ]
        try:
            with codecs.open(gitignore_path, "w", "utf-8") as f:
                f.write("\n".join(content))
            print("Created: .gitignore")
        except: pass
    else:
        # File exists, check if sync_debug.log is ignored
        try:
            with codecs.open(gitignore_path, "r", "utf-8") as f:
                lines = f.readlines()
            
            if not any("*.log" in line for line in lines):
                with codecs.open(gitignore_path, "a", "utf-8") as f:
                    f.write("\n*.log\n")
                print("Updated .gitignore with *.log")
        except: pass

    if not os.path.exists(gitattributes_path):
        content = [
            "# Git LFS configuration for CODESYS project binary",
            "*.project filter=lfs diff=lfs merge=lfs -text",
            "",
            "# Prevent line ending conversion for CODESYS Structured Text files",
            "*.st -text",
            "",
            "# GitHub linguist language detection",
            "*.st linguist-language=Pascal",
            ""
        ]
        try:
            with codecs.open(gitattributes_path, "w", "utf-8") as f:
                f.write("\n".join(content))
            print("Created: .gitattributes")
        except: pass



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
    start_time = time.time()
    print("Export directory: " + export_dir)
    
    # Metadata structure
    current_project_name = safe_str(projects.primary)
    metadata = {
        "project_name": current_project_name,
        "export_timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "autosync": "STOPPED",
        "sync_timeout": 10000,
        "export_xml": False,
        "objects": {}
    }
    
    try:
        if hasattr(projects.primary, "path"):
            metadata["project_path"] = safe_str(projects.primary.path)
    except:
        pass
    
    # Read settings from project properties (Source of Truth)
    from codesys_utils import get_project_prop
    metadata["export_xml"] = get_project_prop("cds-sync-export-xml", False)
    metadata["sync_timeout"] = get_project_prop("cds-sync-timeout", 10000)
    metadata["autosync"] = get_project_prop("cds-sync-autosync", "STOPPED")
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
    
    exported_count = 0
    skipped_count = 0
    
    # Create subdirectories
    src_dir = os.path.join(export_dir, "src")
    xml_dir = os.path.join(export_dir, "xml")
    config_dir = os.path.join(export_dir, "config")
    
    for d in [src_dir, xml_dir, config_dir]:
        if not os.path.exists(d):
            os.makedirs(d)

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
        'src_dir': src_dir,
        'xml_dir': xml_dir,
        'config_dir': config_dir,
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
            if obj_type in managers:
                manager = managers[obj_type]
            elif obj_type in XML_TYPES:
                if not metadata.get("export_xml", False) and obj_type != TYPE_GUIDS["task_config"]:
                    continue
                manager = managers["native"]
            elif obj_type in EXPORTABLE_TYPES:
                manager = managers["default"]
            else:
                continue
                
            if manager.export(obj, context):
                exported_count += 1
            else:
                # Some objects might be skipped intentionally (e.g. no content)
                pass
            
        except Exception as e:
            log_error("Error exporting " + safe_str(obj) + ": " + safe_str(e))
    
    # Cleanup orphaned files (files on disk not in current export)
    if not cleanup_orphaned_files(export_dir, metadata["objects"], silent=silent):
        return
    
    # Debug: Count methods in metadata before saving
    method_count = sum(1 for obj in metadata["objects"].values() if obj.get("type") == TYPE_GUIDS["method"])
    print("DEBUG: Before saving - Total objects: " + str(len(metadata["objects"])) + ", Methods: " + str(method_count))
    
    # Write metadata file with consistent field order (60s timeout for large projects)
    with MetadataLock(export_dir, timeout=60):
        if save_metadata(export_dir, metadata):
            print("Created: _config.json and _metadata.csv")
        else:
            print("Error writing metadata")
            
        # Add library export
        libraries = extract_libraries_from_project(projects.primary)
        if libraries:
            if save_libraries(export_dir, libraries):
                print("Created: _libraries.csv (" + str(len(libraries)) + " libraries)")
            else:
                print("Error writing _libraries.csv")
    
    print("=== Export Complete ===")
    elapsed_time = time.time() - start_time
    print("Exported: " + str(exported_count) + " files")
    print("Skipped: " + str(skipped_count) + " objects (no textual content)")
    print("Time elapsed: {:.2f} seconds".format(elapsed_time))
    print("Completed at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    
    log_info("Export complete! Exported: " + str(exported_count) + " files.")
    
    # Check for silent mode (Non-Blocking UI)
    silent_mode = get_project_prop("cds-sync-silent-mode", False)
    
    if silent_mode:
        try:
            from codesys_ui import show_toast
            show_toast("Export Complete", "Exported: " + str(exported_count) + " files\nTime: {:.2f}s".format(elapsed_time))
        except:
            # Fallback if UI module missing
            print("Export complete (Silent mode active, but UI module failed)")
    else:
        system.ui.info("Export complete!\n\nExported: " + str(exported_count) + " files\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))


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
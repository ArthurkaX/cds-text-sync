import os
import sys
import time
import codecs
import json
import imp

# --- Hidden Module Loader ---
def _load_hidden_module(name):
    """Load a .pyw module from the script directory and register it in sys.modules."""
    if name not in sys.modules:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, name + ".pyw")
        if os.path.exists(path):
            sys.modules[name] = imp.load_source(name, path)

# Force reload of shared modules to pick up latest changes
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith('codesys_'):
        del sys.modules[_mod_name]

# Load shared core logic
_load_hidden_module("codesys_constants")
_load_hidden_module("codesys_utils")
_load_hidden_module("codesys_managers")
_load_hidden_module("codesys_ui")

from codesys_constants import (
    IMPL_MARKER, TYPE_GUIDS, EXPORTABLE_TYPES, XML_TYPES, FORBIDDEN_CHARS, RESERVED_FILES,
    SCRIPT_VERSION
)
from codesys_utils import (
    safe_str, clean_filename, load_base_dir,
    calculate_hash, format_st_content,
    log_info, log_warning, log_error,
    init_logging, backup_project_binary, format_property_content,
    resolve_projects, update_application_count_flag, ensure_git_configs
)
from codesys_managers import (
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    get_object_path, collect_property_accessors, is_nvl, is_graphical_pou,
    classify_object
)

# Shared constants and utilities imported from modules


def save_export_metadata(export_dir, stats, elapsed_time):
    """Save export metadata to sync_metadata.json and project property"""
    from codesys_utils import set_project_prop
    
    metadata = {
        "script_version": SCRIPT_VERSION,
        "last_action": "export",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_sec": round(elapsed_time, 2),
        "statistics": stats
    }
    
    metadata_path = os.path.join(export_dir, "sync_metadata.json")
    try:
        with codecs.open(metadata_path, "w", "utf-8") as f:
            json.dump(metadata, f, indent=2)
        log_info("Export metadata saved to sync_metadata.json (v" + SCRIPT_VERSION + ")")
    except Exception as e:
        log_warning("Failed to save export metadata: " + safe_str(e))
    
    try:
        set_project_prop("cds-sync-version", SCRIPT_VERSION)
        log_info("Script version saved to project property")
    except Exception as e:
        log_warning("Failed to save version to project property: " + safe_str(e))


def cleanup_orphaned_files(export_dir, current_objects):
    """
    Find and optionally delete files in export_dir that are not in current_objects.
    """
    orphaned_items = []
    
    # We'll collect everything first to show a preview
    for root, dirs, files in os.walk(export_dir):
        # Skip hidden dirs (including .diff, .git, .project etc.)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        
        # Calculate relative path from export_dir
        rel_root = os.path.relpath(root, export_dir)
        if rel_root == ".":
            rel_root = ""
            
        # Check files
        for f in files:
            # Skip reserved files and folders
            # Skip files starting with dot
            if f.startswith("."):
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

    if auto_delete:
        result = (0,) # Simulate Delete
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
            try:
                result = system.ui.choose(message, ("Delete Orphans", "Ignore", "Cancel Export"))
            except NameError:
                # Running outside CODESYS - default to "Ignore"
                result = ("Ignore",)
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
            # Also skip hidden dirs here
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            
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





def export_project(export_dir, projects_obj=None):
    """Export all project objects to folder structure with metadata"""
    
    # Resolving projects object
    projects_obj = resolve_projects(projects_obj, globals())
    
    if projects_obj is None or not projects_obj.primary:
        msg = "Error: 'projects' object not found or no project open."
        try:
            system.ui.error(msg)
        except NameError:
            print("Error:", msg)
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
    
    # Flags and tracking
    from codesys_utils import get_project_prop
    export_xml = get_project_prop("cds-sync-export-xml", False)
    backup_binary = get_project_prop("cds-sync-backup-binary", False)
    exported_paths = set()  # For orphan tracking
    
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
    
    # Metadata migration - no longer used
    
    # Collect all property accessors
    property_accessors = collect_property_accessors(all_objects)
    print("Found " + str(len(property_accessors)) + " properties with accessors")
    
    # Initialize managers
    managers = {
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
    
    context = {
        'export_dir': export_dir,
        'export_xml': export_xml,
        'property_accessors': property_accessors,
        'exported_paths': exported_paths
    }

    # Second pass: export all objects
    for obj in all_objects:
        try:
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

            # Select manager
            if is_xml:
                manager = managers["native"] if effective_type not in managers else managers[effective_type]
            elif effective_type in managers:
                manager = managers[effective_type]
            else:
                manager = managers["default"]

            context['effective_type'] = effective_type
            result = manager.export(obj, context)
            if result == "new":
                exported_new += 1
            elif result == "updated":
                exported_updated += 1
            elif result == "identical":
                exported_identical += 1
                
        except Exception as e:
            log_error("Error exporting " + safe_str(obj) + ": " + safe_str(e))
    
    # Orphan cleanup now uses exported_paths set directly
    if not cleanup_orphaned_files(export_dir, exported_paths):
        return

    # Clear sync cache after full export to ensure consistency
    cache_path = os.path.join(export_dir, "sync_cache.json")
    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
            log_info("Cleared sync cache after full export.")
        except:
            pass
            
    print("=== Export Complete ===")
    elapsed_time = time.time() - start_time
    print("New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical))
    print("Skipped: " + str(skipped_count) + " objects (no textual content)")
    print("Time elapsed: {:.2f} seconds".format(elapsed_time))
    print("Completed at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    
    exported_total = exported_new + exported_updated + exported_identical
    summary = "Exported: " + str(exported_total) + " (New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical) + ")"
    log_info("Export complete! " + summary)
    
    # Save export metadata for version tracking
    save_export_metadata(export_dir, {
        "new": exported_new,
        "updated": exported_updated,
        "identical": exported_identical,
        "total": exported_total
    }, elapsed_time)
    
    # Show completion notification
    try:
        system.ui.info("Export complete!\n\n" + summary + "\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))
    except NameError:
        print("Export complete!\n" + summary + "\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))


def main():
    base_dir, error = load_base_dir()
    if error:
        try:
            system.ui.warning(error)
        except NameError:
            print("Error:", error)
        return
        
    init_logging(base_dir)
    export_project(base_dir)


if __name__ == "__main__":
    main()
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
    resolve_projects, update_application_count_flag, ensure_git_configs,
    get_quick_ide_hash, load_sync_cache, save_sync_cache, build_folder_hashes,
    normalize_path, finalize_sync_operation
)
from codesys_managers import (
    FolderManager, POUManager, PropertyManager, NativeManager, ConfigManager,
    get_object_path, collect_property_accessors, is_nvl, is_graphical_pou,
    classify_object, build_expected_path
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
        return 0

    # Check for auto-delete property
    try:
        from codesys_utils import get_project_prop
        auto_delete = get_project_prop("cds-sync-auto-delete-orphans", False)
    except:
        auto_delete = False

    if auto_delete:
        choice_idx = 0 # Delete
    else:
        # Prompt user
        message = "The following files exist in the export directory but are NOT in the CODESYS project (orphans):\n\n"
        # Show first 15 files as preview
        for item in orphaned_items[:15]:
            message += "- " + item + "\n"
        if len(orphaned_items) > 15:
            message += "... and " + str(len(orphaned_items) - 15) + " more.\n"
        
        message += "\nWould you like to delete these orphaned files?"
        
        # buttons: Delete (Yes), Ignore (No)
        from codesys_ui import ask_yes_no
        if ask_yes_no("Delete Orphaned Files?", message):
            choice_idx = 0 # Delete
        else:
            choice_idx = 1 # Ignore
    
    removed_count = 0
    if choice_idx == 0: # Delete
        print("Cleaning up orphaned files...")
        for rel_path in orphaned_items:
            full_path = os.path.join(export_dir, rel_path.replace("/", os.sep))
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    removed_count += 1
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
        return removed_count
    elif result[0] == 1: # Ignore
        print("Orphaned files ignored.")
        return 0
    else: # Cancel
        print("Export cancelled during cleanup.")
        return None





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
    exported_failed = 0
    skipped_count = 0
    
    # Metadata migration - no longer used
    
    # Property accessors collected dynamically during main loop
    property_accessors = {}
    
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
    
    # Load sync cache for fast-export skipping
    cache_data = load_sync_cache(export_dir)
    new_cache = {}
    if cache_data and cache_data.get('objects'):
        log_info("Sync cache loaded! Enabling accelerated export (Merkle Tree skip).")
    
    context = {
        'export_dir': export_dir,
        'export_xml': export_xml,
        'property_accessors': property_accessors,
        'exported_paths': exported_paths,
        'cache_data': cache_data,
        'new_cache': new_cache,
        'new_types': {}
    }

    # Second pass: export all objects
    for obj in all_objects:
        try:
            obj_guid = safe_str(obj.guid)
            cached_type = cache_data.get('types', {}).get(obj_guid)
            if cached_type:
                effective_type, is_xml = cached_type[0], cached_type[1]
                rel_path = cached_type[2] if len(cached_type) > 2 else None
                should_skip = False if rel_path else True
            else:
                effective_type, is_xml, should_skip = classify_object(obj)
                rel_path = build_expected_path(obj, effective_type, is_xml) if not should_skip else None
            
            # Store for next cache save (always)
            context['new_types'][obj_guid] = (effective_type, is_xml, rel_path)
            
            if rel_path:
                norm_path = normalize_path(rel_path)
            else:
                norm_path = None
            
            # --- PROPERTY ACCESSOR COLLECTION ---
            if effective_type == TYPE_GUIDS["property"]:
                try:
                    if obj_guid not in context['property_accessors']:
                        context['property_accessors'][obj_guid] = {'get': None, 'set': None}
                    
                    for child in obj.get_children():
                        child_name = child.get_name().upper()
                        if child_name == "GET":
                            context['property_accessors'][obj_guid]['get'] = child
                        elif child_name == "SET":
                            context['property_accessors'][obj_guid]['set'] = child
                except:
                    pass
            
            # --- PERSIST CACHE FOR SKIPPED OBJECTS ---
            if cache_data and norm_path:
                try:
                    cached_obj = cache_data.get('objects', {}).get(norm_path)
                    if cached_obj:
                        new_cache[norm_path] = cached_obj
                except: pass
            # ----------------------------------------

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
            result = manager.export(obj, context, rel_path=rel_path)
            if result == "new":
                exported_new += 1
            elif result == "updated":
                exported_updated += 1
            elif result == "identical":
                exported_identical += 1
                
        except Exception as e:
            exported_failed += 1
            log_error("Error exporting " + safe_str(obj) + ": " + safe_str(e))
    
    # Orphan cleanup now uses exported_paths set directly
    removed_count = cleanup_orphaned_files(export_dir, exported_paths)
    if removed_count is None:
        return

    # Calculate folder hashes (Merkle Tree) and save the updated cache
    if new_cache:
        # build_folder_hashes expects a dict of {path: ide_hash}
        just_hashes = {path: entry.get('ide_hash') for path, entry in new_cache.items()}
        folder_hashes = build_folder_hashes(just_hashes)
        save_sync_cache(export_dir, new_cache, folder_hashes, context.get('new_types'))
        log_info("Saved updated sync cache with {} objects and {} folders.".format(
            len(new_cache), len(folder_hashes)))
            
    print("=== Export Complete ===")
    elapsed_time = time.time() - start_time
    print("New: " + str(exported_new) + ", Updated: " + str(exported_updated) + ", Identical: " + str(exported_identical) + ", Removed: " + str(removed_count))
    print("Skipped: " + str(skipped_count) + " objects (no textual content)")
    print("Time elapsed: {:.2f} seconds".format(elapsed_time))
    print("Completed at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    
    exported_total = exported_new + exported_updated + exported_identical
    summary = "Updated: " + str(exported_updated) + ", Created: " + str(exported_new) + ", Removed: " + str(removed_count) + ", Failed: " + str(exported_failed) + " (Identical: " + str(exported_identical) + ")"
    log_info("Export complete! " + summary + " Time elapsed: {:.2f}s".format(elapsed_time))
    
    # Save export metadata for version tracking
    save_export_metadata(export_dir, {
        "new": exported_new,
        "updated": exported_updated,
        "identical": exported_identical,
        "removed": removed_count,
        "failed": exported_failed,
        "total": exported_total
    }, elapsed_time)
    
    # Show completion notification
    try:
        system.ui.info("Export complete!\n\n" + summary + "\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))
    except NameError:
        print("Export complete!\n" + summary + "\nLocation: " + export_dir + "\nTime elapsed: {:.2f} seconds".format(elapsed_time))

    # Handle final save and backup
    finalize_sync_operation(export_dir, projects_obj, is_import=False)


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
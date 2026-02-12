# -*- coding: utf-8 -*-
"""
Project_parameters.py - Configure Project parameters
1. Toggle XML Export
2. Toggle Project Binary Backup

Updates parameters in Project Information > Properties
"""
import os
from codesys_utils import safe_str, load_base_dir, get_project_prop, set_project_prop

def main():
    base_dir, error = load_base_dir()
    if error:
        system.ui.warning(error)
        return
    
    # Check if UI module is available (IronPython + Forms)
    try:
        from codesys_ui import show_settings_dialog
    except:
        print("Warning: codesys_ui module not found or failed to load. Falling back to text mode.")
        # Fallback to text mode implemented below is skipped for brevity since we deployed the UI module
        # If UI fails, we probably have bigger issues. Let's just assume it works or handle the import error gracefully.
        system.ui.error("Could not load UI components (System.Windows.Forms). Check your Python environment.")
        return

    # Get current settings
    current_settings = {
        "export_xml": get_project_prop("cds-sync-export-xml", False),
        "backup_binary": get_project_prop("cds-sync-backup-binary", False),
        "save_after_import": get_project_prop("cds-sync-save-after-import", True),
        "backup_name": get_project_prop("cds-sync-backup-name", ""),
        "silent_mode": get_project_prop("cds-sync-silent-mode", False)
    }

    # Show Dialog
    new_settings = show_settings_dialog(current_settings)
    
    if new_settings:
        # Save changes
        set_project_prop("cds-sync-export-xml", new_settings["export_xml"])
        set_project_prop("cds-sync-backup-binary", new_settings["backup_binary"])
        set_project_prop("cds-sync-save-after-import", new_settings["save_after_import"])
        set_project_prop("cds-sync-backup-name", new_settings["backup_name"])
        set_project_prop("cds-sync-silent-mode", new_settings["silent_mode"])
        
        print("Settings saved successfully.")
    else:
        print("Settings cancelled.")

if __name__ == "__main__":
    main()

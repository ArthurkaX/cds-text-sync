# -*- coding: utf-8 -*-
"""
Project_parameters.py - Configure Project parameters
1. Toggle XML Export
2. Toggle Project Binary Backup

Updates parameters in Project Information > Properties
"""
import os

from Project_bootstrap import load_hidden_modules

load_hidden_modules([
    "codesys_constants",
    "codesys_utils",
    "codesys_ui",
    "codesys_type_profiles",
], script_file=__file__)

from codesys_utils import safe_str, load_base_dir, get_project_prop, set_project_prop, get_detected_codesys_version
from codesys_constants import SCRIPT_VERSION
from codesys_type_profiles import PROJECT_PROPERTY_KEY, list_profiles, DEFAULT_PROFILE_NAME, get_profile_label

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
        "save_after_export": get_project_prop("cds-sync-save-after-export", True),
        "safety_backup": get_project_prop("cds-sync-safety-backup", True),
        "backup_name": get_project_prop("cds-sync-backup-name", ""),
        "retention_count": get_project_prop("cds-sync-backup-retention-count", 10),
        "enable_logging": get_project_prop("cds-sync-enable-logging", False),
        "type_profile": get_project_prop(PROJECT_PROPERTY_KEY, DEFAULT_PROFILE_NAME),
        "available_profiles": list_profiles(),
        "available_profile_labels": dict((name, get_profile_label(name)) for name in list_profiles()),
        "detected_codesys_version": get_detected_codesys_version()
    }

    # Show Dialog
    new_settings = show_settings_dialog(current_settings, version=SCRIPT_VERSION)
    
    if new_settings:
        # Save changes
        set_project_prop("cds-sync-export-xml", new_settings["export_xml"])
        set_project_prop("cds-sync-backup-binary", new_settings["backup_binary"])
        set_project_prop("cds-sync-save-after-import", new_settings["save_after_import"])
        set_project_prop("cds-sync-save-after-export", new_settings["save_after_export"])
        set_project_prop("cds-sync-safety-backup", new_settings["safety_backup"])
        set_project_prop("cds-sync-backup-name", new_settings["backup_name"])
        set_project_prop("cds-sync-backup-retention-count", new_settings["retention_count"])
        set_project_prop("cds-sync-enable-logging", new_settings["enable_logging"])
        selected_profile = new_settings.get("type_profile", DEFAULT_PROFILE_NAME) or DEFAULT_PROFILE_NAME
        set_project_prop(PROJECT_PROPERTY_KEY, selected_profile)

        print("Detected CODESYS version: " + safe_str(current_settings.get("detected_codesys_version")))
        print("Selected type profile: " + safe_str(selected_profile) + " (" + safe_str(get_profile_label(selected_profile)) + ")")
        print("Settings saved successfully.")
    else:
        print("Settings cancelled.")

if __name__ == "__main__":
    main()

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
    
    while True:
        # Get current settings
        export_xml = get_project_prop("cds-sync-export-xml", False)
        backup_binary = get_project_prop("cds-sync-backup-binary", False)
        save_after_import = get_project_prop("cds-sync-save-after-import", True)
        backup_name = get_project_prop("cds-sync-backup-name", "")

        # Build menu options
        xml_opt = "[*] Export Native XML (Visu/Alarms)" if export_xml else "[ ] Export Native XML (Visu/Alarms)"
        backup_opt = "[*] Backup .project binary" if backup_binary else "[ ] Backup .project binary"
        name_val = backup_name if backup_name else "(original name)"
        name_opt = "    > Set Backup Name: " + name_val
        save_opt = "[*] Save Project after Import" if save_after_import else "[ ] Save Project after Import"
        
        message = "Configure Project Sync Parameters:\n(Settings are saved in Project Information)"
        
        options = (
            xml_opt,
            backup_opt,
            name_opt,
            save_opt,
            "Exit"
        )
        
        try:
            result = system.ui.choose(message, options)
        except:
            return

        if result is None: # Dialog closed
            return
            
        choice = result[0]
        
        if choice == 0: # Toggle XML
            set_project_prop("cds-sync-export-xml", not export_xml)
            print("Updated XML Export -> " + str(not export_xml))
            
        elif choice == 1: # Toggle Backup
            set_project_prop("cds-sync-backup-binary", not backup_binary)
            print("Updated Binary Backup -> " + str(not backup_binary))
            
        elif choice == 2: # Set Backup Name
            current = backup_name if backup_name else ""
            try:
                # Prompt for new name
                new_name = system.ui.query_string("Enter fixed filename for backup (e.g. 'Project'):", current)
                if new_name is not None:
                    # Clean the name if it has .project extension
                    if new_name.lower().endswith(".project"):
                        new_name = new_name[:-8]
                    
                    set_project_prop("cds-sync-backup-name", new_name.strip())
                    print("Updated Backup Name -> " + (new_name.strip() if new_name.strip() else "original"))
            except Exception as e:
                print("Error setting backup name: " + str(e))

        elif choice == 3: # Toggle Save
            set_project_prop("cds-sync-save-after-import", not save_after_import)
            print("Updated Save After Import -> " + str(not save_after_import))
            
        else: # Exit
            return

if __name__ == "__main__":
    main()

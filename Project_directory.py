# -*- coding: utf-8 -*-
import os

def set_base_directory():
    # CODESYS provides the 'system' object for UI interactions
    if not "projects" in globals() or not projects.primary:
        system.ui.error("No project open! Please open a project to set its sync directory.")
        return

    proj = projects.primary
    
    # Get Project Information object safely
    info = None
    if hasattr(proj, "get_project_info"):
        info = proj.get_project_info()
    elif hasattr(proj, "project_info"):
        info = proj.project_info
        
    if not info:
        system.ui.error("Could not access Project Information!")
        return

    # Try to read current value for better UX
    initial_dir = ""
    try:
        props = info.values if hasattr(info, "values") else info
        if "cds-sync-folder" in props: # Dictionary-like access
             initial_dir = props["cds-sync-folder"]
    except:
        pass

    # Offer choice: Browse or Manual Input
    choice = system.ui.choose(
        "How would you like to set the sync directory?\n\n" +
        "Browse: Select a folder using file browser\n" +
        "Manual: Enter path manually (supports relative paths like ./ or ./foldername/)",
        ("Browse", "Manual Input", "Cancel")
    )
    
    if not choice or choice[0] == 2:  # Cancel
        print("Operation cancelled by user.")
        return
    
    selected_path = None
    
    if choice[0] == 0:  # Browse
        selected_path = system.ui.browse_directory_dialog("Select Sync Directory for this Project", initial_dir)
    else:  # Manual Input
        # Create a simple input dialog using Windows Forms
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            from System.Windows.Forms import Form, Label, TextBox, Button, DialogResult, FormBorderStyle, FormStartPosition
            from System.Drawing import Size, Point, Font, FontStyle
            
            # Create form
            form = Form()
            form.Text = "Enter Sync Directory Path"
            form.Size = Size(500, 220)
            form.FormBorderStyle = FormBorderStyle.FixedDialog
            form.StartPosition = FormStartPosition.CenterScreen
            form.MaximizeBox = False
            form.MinimizeBox = False
            
            # Instructions label
            lbl_instructions = Label()
            lbl_instructions.Text = "Examples:\n" + \
                                   "  ./                          - Project directory\n" + \
                                   "  ./folderName/      - 'folderName' folder in project directory\n" + \
                                   "  C:\\MySync\\         - Absolute path\n\n" + \
                                   "Relative paths (starting with ./) are resolved relative to the project file location."
            lbl_instructions.Location = Point(20, 15)
            lbl_instructions.Size = Size(460, 100)
            form.Controls.Add(lbl_instructions)
            
            # Path label
            lbl_path = Label()
            lbl_path.Text = "Path:"
            lbl_path.Location = Point(20, 125)
            lbl_path.AutoSize = True
            form.Controls.Add(lbl_path)
            
            # Path textbox
            txt_path = TextBox()
            txt_path.Location = Point(70, 122)
            txt_path.Size = Size(400, 20)
            txt_path.Text = initial_dir if initial_dir else "./"
            form.Controls.Add(txt_path)
            
            # OK button
            btn_ok = Button()
            btn_ok.Text = "OK"
            btn_ok.DialogResult = DialogResult.OK
            btn_ok.Location = Point(300, 155)
            btn_ok.Size = Size(80, 25)
            form.Controls.Add(btn_ok)
            form.AcceptButton = btn_ok
            
            # Cancel button
            btn_cancel = Button()
            btn_cancel.Text = "Cancel"
            btn_cancel.DialogResult = DialogResult.Cancel
            btn_cancel.Location = Point(390, 155)
            btn_cancel.Size = Size(80, 25)
            form.Controls.Add(btn_cancel)
            form.CancelButton = btn_cancel
            
            # Show dialog
            result = form.ShowDialog()
            if result == DialogResult.OK:
                selected_path = txt_path.Text.strip()
            else:
                selected_path = None
                
        except Exception as e:
            system.ui.error("Failed to create input dialog: " + str(e))
            selected_path = None
    
    if selected_path:
        # Normalize path separators
        selected_path = selected_path.replace('/', os.sep).replace('\\', os.sep)
        
        # Check if path is relative
        is_relative = selected_path.startswith('.' + os.sep) or selected_path == '.'
        
        # Save strictly to project properties
        try:
            props = info.values if hasattr(info, "values") else info
            props["cds-sync-folder"] = selected_path
            
            # Save current PC name to detect project transfers
            try:
                import socket
                props["cds-sync-pc"] = socket.gethostname()
            except:
                pass
            
            if is_relative:
                print("Success: Project sync directory set to relative path: " + selected_path)
                system.ui.info("Sync directory saved as relative path.\n\nThis path will be resolved relative to the project file location at runtime.\n\nPath: " + selected_path)
            else:
                print("Success: Project sync directory updated to: " + selected_path)
                system.ui.info("Sync directory saved to Project Information > Properties.")
        except Exception as e:
            system.ui.error("Could not save to project properties: " + str(e))
            return
        
        # Check _metadata.json for project path mismatch (only for absolute paths)
        if not is_relative:
            try:
                metadata_path = os.path.join(selected_path, "_metadata.json")
                if os.path.exists(metadata_path):
                    import json
                    with open(metadata_path, 'r') as f:
                        data = json.load(f)
                    
                    json_path = data.get('project_path', '')
                    
                    # Safe way to get current project path
                    current_path = ""
                    try:
                        if "projects" in globals() and projects.primary:
                            current_path = projects.primary.path
                    except:
                        pass
                    
                    if current_path and json_path and json_path != current_path:
                        message = "Metadata Mismatch Detected!\n\n"
                        message += "The selected directory contains exports from a different project:\n"
                        message += "Metadata Path: " + json_path + "\n"
                        message += "Current Project: " + current_path + "\n\n"
                        message += "Do you want to update the metadata to match the current project?"
                        
                        # Offer to update
                        res = system.ui.choose(message, ("Yes, Update Metadata", "No, Keep As Is"))
                        
                        if res and res[0] == 0:
                            data['project_path'] = current_path
                            try:
                                data['project_name'] = str(projects.primary)
                            except:
                                pass
                                
                            with open(metadata_path, 'w') as f:
                                json.dump(data, f, indent=2)
                            print("Updated _metadata.json project path to current project.")
                            system.ui.info("Metadata updated successfully.")
                            
            except Exception as e:
                print("Warning: Failed to check metadata: " + str(e))

    else:
        print("Operation cancelled by user.")

if __name__ == "__main__":
    set_base_directory()

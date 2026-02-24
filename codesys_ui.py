# -*- coding: utf-8 -*-
"""
codesys_ui.py - Modern UI components for CODESYS scripts
"""
import clr
import os
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Application, Form, Label, CheckBox, Button, FormBorderStyle, 
        DialogResult, FormStartPosition, NotifyIcon, ToolTipIcon, TextBox,
        Control, Keys
    )
    from System.Drawing import Size, Point, Font, FontStyle, SystemIcons
except:
    # Fallback if forms not available (e.g. Linux/Headless)
    pass

import time
from System.Threading import Thread, ThreadStart

def show_toast(title, message, timeout=3000):
    """
    Shows a Windows system tray notification that doesn't block the user.
    """
    def run_toast():
        try:
            notification = NotifyIcon()
            notification.Icon = SystemIcons.Information
            notification.Visible = True
            
            # Show balloon
            notification.ShowBalloonTip(timeout, title, message, ToolTipIcon.Info)
            
            # Keep alive briefly then cleanup
            time.sleep(timeout / 1000.0 + 1.0) 
            notification.Visible = False
            notification.Dispose()
        except:
            pass

    # Run in a daemon-like thread
    t = Thread(ThreadStart(run_toast))
    t.Start()

class SettingsForm(Form):
    def __init__(self, current_settings):
        self.Text = "CODESYS Sync Settings"
        self.Size = Size(420, 360) # Increased height for more options
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        
        # Heading
        lbl = Label()
        lbl.Text = "Configure Sync Behavior"
        lbl.Location = Point(20, 20)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 12, FontStyle.Bold)
        self.Controls.Add(lbl)
        
        # Group 1: Export Settings
        y = 60
        self.chk_xml = CheckBox()
        self.chk_xml.Text = "Export Native XML (Visu/Alarms)"
        self.chk_xml.Location = Point(30, y)
        self.chk_xml.Size = Size(350, 24)
        self.chk_xml.Checked = current_settings.get("export_xml", False)
        self.Controls.Add(self.chk_xml)
        
        y += 30
        self.chk_bin = CheckBox()
        self.chk_bin.Text = "Backup .project Binary (Git LFS)"
        self.chk_bin.Location = Point(30, y)
        self.chk_bin.Size = Size(350, 24)
        self.chk_bin.Checked = current_settings.get("backup_binary", False)
        self.Controls.Add(self.chk_bin)

        # Subsection: Backup Name
        y += 30
        lbl_name = Label()
        lbl_name.Text = "Backup Name (Optional):"
        lbl_name.Location = Point(50, y+3)
        lbl_name.AutoSize = True
        self.Controls.Add(lbl_name)
        
        self.txt_backup_name = TextBox()
        self.txt_backup_name.Location = Point(200, y)
        self.txt_backup_name.Size = Size(150, 20)
        self.txt_backup_name.Text = current_settings.get("backup_name", "")
        self.Controls.Add(self.txt_backup_name)

        # Group 2: Import Settings
        y += 40
        self.chk_save = CheckBox()
        self.chk_save.Text = "Save Project after Import"
        self.chk_save.Location = Point(30, y)
        self.chk_save.Size = Size(350, 24)
        self.chk_save.Checked = current_settings.get("save_after_import", True)
        self.Controls.Add(self.chk_save)

        y += 30
        self.chk_safety = CheckBox()
        self.chk_safety.Text = "Timestamped Backup before Import"
        self.chk_safety.Location = Point(30, y)
        self.chk_safety.Size = Size(350, 24)
        self.chk_safety.Checked = current_settings.get("safety_backup", True)
        self.Controls.Add(self.chk_safety)

        # Group 3: UX Settings
        y += 40
        self.chk_silent = CheckBox()
        self.chk_silent.Text = "Silent Mode (Toast Notifications)"
        self.chk_silent.Location = Point(30, y)
        self.chk_silent.Size = Size(350, 24)
        self.chk_silent.Checked = current_settings.get("silent_mode", False)
        self.Controls.Add(self.chk_silent)

        # Buttons
        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.DialogResult = DialogResult.Cancel
        btn_cancel.Location = Point(290, 280)
        self.Controls.Add(btn_cancel)

        btn_save = Button()
        btn_save.Text = "Save Settings"
        btn_save.DialogResult = DialogResult.OK
        btn_save.Location = Point(160, 280)
        btn_save.Size = Size(120, 23)
        self.Controls.Add(btn_save)
        self.AcceptButton = btn_save
        self.CancelButton = btn_cancel

    def get_results(self):
        return {
            "export_xml": self.chk_xml.Checked,
            "backup_binary": self.chk_bin.Checked,
            "backup_name": self.txt_backup_name.Text.strip(),
            "save_after_import": self.chk_save.Checked,
            "safety_backup": self.chk_safety.Checked,
            "silent_mode": self.chk_silent.Checked
        }

def show_settings_dialog(current_settings):
    try:
        form = SettingsForm(current_settings)
        result = form.ShowDialog()
        if result == DialogResult.OK:
            return form.get_results()
    except Exception as e:
        print("Error showing settings dialog: " + str(e))
    return None


class CompareResultsForm(Form):
    """WinForms dialog showing comparison results with checkboxes"""
    
    IMPORT = "import"
    EXPORT = "export"
    CLOSE = "close"
    
    def __init__(self, different, new_in_ide, new_on_disk, unchanged_count):
        self.Text = "cds-text-sync: Comparison Results"
        self.Size = Size(500, 480)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.result_action = self.CLOSE
        self.checkboxes = []
        
        y = 15
        
        # Header
        lbl = Label()
        lbl.Text = "Differences found between IDE and Disk."
        lbl.Location = Point(15, y)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 10, FontStyle.Bold)
        self.Controls.Add(lbl)
        y += 30
        
        lbl2 = Label()
        lbl2.Text = "Select the objects you want to synchronize:"
        lbl2.Location = Point(15, y)
        lbl2.AutoSize = True
        self.Controls.Add(lbl2)
        y += 28
        
        # Add sections
        if different:
            y = self._add_section(y, "Modified (IDE and Disk differ):", different, "different")
        if new_in_ide:
            y = self._add_section(y, "New in IDE (not yet exported):", new_in_ide, "new")
        if new_on_disk:
            # Map path/file_path to consistent structure for display
            mapped_new = []
            for item in new_on_disk:
                mapped_new.append({
                    "name": item["name"], "path": item["path"], "type": "new file",
                    "file_path": item["file_path"]
                })
            y = self._add_section(y, "New on Disk (need Import):", mapped_new, "new_on_disk")
        
        # Summary
        y += 5
        lbl_sum = Label()
        lbl_sum.Text = "M:" + str(len(different)) + "  +:" + str(len(new_in_ide)) + "  *:" + str(len(new_on_disk or [])) + "  =:" + str(unchanged_count)
        lbl_sum.Location = Point(15, y)
        lbl_sum.AutoSize = True
        self.Controls.Add(lbl_sum)
        y += 30
        
        # Select All / None
        btn_all = Button()
        btn_all.Text = "All"
        btn_all.Location = Point(15, y)
        btn_all.Size = Size(55, 25)
        btn_all.Click += self._select_all
        self.Controls.Add(btn_all)
        
        btn_none = Button()
        btn_none.Text = "None"
        btn_none.Location = Point(75, y)
        btn_none.Size = Size(55, 25)
        btn_none.Click += self._select_none
        self.Controls.Add(btn_none)
        
        # Action buttons
        btn_close = Button()
        btn_close.Text = "Close"
        btn_close.Location = Point(380, y)
        btn_close.Size = Size(90, 28)
        btn_close.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_close)
        self.CancelButton = btn_close
        
        btn_export = Button()
        btn_export.Text = "Export to Disk"
        btn_export.Location = Point(260, y)
        btn_export.Size = Size(110, 28)
        btn_export.Click += self._on_export
        self.Controls.Add(btn_export)
        
        btn_import = Button()
        btn_import.Text = "Import to IDE"
        btn_import.Location = Point(140, y)
        btn_import.Size = Size(110, 28)
        btn_import.Click += self._on_import
        self.Controls.Add(btn_import)
        
        # Resize form to fit content
        self.Size = Size(500, y + 65)
    
    def _add_section(self, y, title, items, direction):
        """Add a labeled section with checkboxes and optional diff buttons"""
        lbl = Label()
        lbl.Text = title
        lbl.Location = Point(15, y)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.Controls.Add(lbl)
        y += 22
        
        for item in items[:15]:
            cb = CheckBox()
            cb.Text = item["name"] + "  [" + item["type"] + "]"
            cb.Location = Point(30, y)
            cb.Size = Size(380, 20)
            cb.Checked = True
            cb.Tag = (item, direction)
            self.Controls.Add(cb)
            self.checkboxes.append(cb)
            
            # Add Diff button if both contents are available
            has_ide = item.get("ide_content", "")
            has_disk = item.get("disk_content", "")
            if has_ide or has_disk:
                btn_diff = Button()
                btn_diff.Text = "Diff"
                btn_diff.Location = Point(418, y - 1)
                btn_diff.Size = Size(48, 21)
                btn_diff.Tag = item
                btn_diff.Click += self._on_diff_click
                btn_diff.Font = Font("Segoe UI", 7)
                self.Controls.Add(btn_diff)
            
            y += 22
        
        if len(items) > 15:
            lbl_more = Label()
            lbl_more.Text = "... and " + str(len(items) - 15) + " more"
            lbl_more.Location = Point(45, y)
            lbl_more.AutoSize = True
            self.Controls.Add(lbl_more)
            y += 20
        
        y += 8
        return y
    
    def _select_all(self, sender, event):
        for cb in self.checkboxes:
            cb.Checked = True
    
    def _select_none(self, sender, event):
        for cb in self.checkboxes:
            cb.Checked = False
    
    def _on_diff_click(self, sender, event):
        """Open side-by-side diff viewer for the clicked item."""
        item = sender.Tag
        if not item:
            return
        
        # Check if Ctrl key is pressed
        is_ctrl_pressed = Control.ModifierKeys == Keys.Control
        
        if is_ctrl_pressed:
            # Save both file versions to /diff/ directory
            try:
                self._save_diff_files(item)
            except Exception as e:
                print("Error saving diff files: " + str(e))
        else:
            # Normal diff dialog behavior
            try:
                from codesys_ui_diff import show_diff_dialog
                ide_text = item.get("ide_content", "")
                disk_text = item.get("disk_content", "")
                obj_name = item.get("name", "Unknown")
                show_diff_dialog(disk_text, ide_text, 
                               "Disk (Folder)", "IDE (Project)", 
                               obj_name)
            except Exception as e:
                print("Error opening diff: " + str(e))
    
    def _on_import(self, sender, event):
        self.result_action = self.IMPORT
        self.DialogResult = DialogResult.OK
        self.Close()
    
    def _on_export(self, sender, event):
        self.result_action = self.EXPORT
        self.DialogResult = DialogResult.OK
        self.Close()
    
    def _save_diff_files(self, item):
        """Save both IDE and disk file versions to /.diff/ directory in project folder."""
        # Get file contents and name
        ide_content = item.get("ide_content", "")
        disk_content = item.get("disk_content", "")
        obj_name = item.get("name", "Unknown")
        rel_path = item.get("path", "")
        
        # Clean the filename for safe file system usage
        safe_name = obj_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        ext = os.path.splitext(rel_path)[1] if rel_path else ".st"
        
        # Resolve project export directory
        from codesys_utils import load_base_dir
        base_dir, _ = load_base_dir()
        if not base_dir:
            # Fallback to current script directory if project not configured
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        diff_dir = os.path.join(base_dir, ".diff")
        if not os.path.exists(diff_dir):
            try:
                os.makedirs(diff_dir)
            except:
                pass
        
        # Save IDE version
        ide_filename = "ide_{0}{1}".format(safe_name, ext)
        ide_path = os.path.join(diff_dir, ide_filename)
        import codecs
        try:
            with codecs.open(ide_path, 'w', 'utf-8') as f:
                f.write(ide_content)
            
            # Save disk version  
            disk_filename = "disk_{0}{1}".format(safe_name, ext)
            disk_path = os.path.join(diff_dir, disk_filename)
            with codecs.open(disk_path, 'w', 'utf-8') as f:
                f.write(disk_content)
            
            # Show notification
            msg = "Saved versions of '{0}' to {1}".format(obj_name, diff_dir)
            show_toast("Diff Files Saved", msg, timeout=4000)
        except Exception as e:
            print("Failed to save diff files: " + str(e))
    
    def get_selected(self):
        """Return list of selected items with their direction tags"""
        selected = []
        for cb in self.checkboxes:
            if cb.Checked and cb.Tag:
                item, direction = cb.Tag
                selected.append(item)
        return selected


def show_compare_dialog(different, new_in_ide, new_on_disk, unchanged_count):
    """Show the comparison results dialog. Returns (action, selected_items)"""
    try:
        form = CompareResultsForm(different, new_in_ide, new_on_disk, unchanged_count)
        result = form.ShowDialog()
        if result == DialogResult.OK:
            return form.result_action, form.get_selected()
    except Exception as e:
        print("Error showing compare dialog: " + str(e))
    return CompareResultsForm.CLOSE, []

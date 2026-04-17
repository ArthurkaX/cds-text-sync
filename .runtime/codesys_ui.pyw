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
        Control, Keys, Panel, RichTextBoxScrollBars, BorderStyle, ComboBox,
        MessageBox, MessageBoxButtons, MessageBoxIcon, FlatStyle
    )
    from System.Drawing import Size, Point, Font, FontStyle, SystemIcons, Color, ContentAlignment
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

def ask_yes_no(title, message):
    """
    Shows a standard Windows Yes/No dialog. 
    Returns True for Yes, False for No or Cancel.
    Avoids the CODESYS radio-button based choose dialog.
    """
    try:
        from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult
        result = MessageBox.Show(message, title, MessageBoxButtons.YesNo, MessageBoxIcon.Question)
        return result == DialogResult.Yes
    except Exception as e:
        print("ask_yes_no error: " + str(e))
        # Fallback to pure CODESYS prompt if WinForms fails
        try:
            import __main__
            if hasattr(__main__, "system"):
                res = __main__.system.ui.prompt(message, __main__.PromptChoice.YesNo, __main__.PromptResult.No)
                return res == __main__.PromptResult.Yes
        except:
            pass
        return False

def ask_yes_no_cancel(title, message):
    """
    Shows a Windows Yes/No/Cancel dialog.
    Returns "yes", "no", or "cancel".
    """
    try:
        from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult
        result = MessageBox.Show(message, title, MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question)
        if result == DialogResult.Yes: return "yes"
        if result == DialogResult.No: return "no"
        return "cancel"
    except Exception as e:
        print("ask_yes_no_cancel error: " + str(e))
        # Fallback to pure CODESYS prompt
        try:
            import __main__
            if hasattr(__main__, "system"):
                res = __main__.system.ui.prompt(message, __main__.PromptChoice.YesNoCancel, __main__.PromptResult.Cancel)
                if res == __main__.PromptResult.Yes: return "yes"
                if res == __main__.PromptResult.No: return "no"
        except:
            pass
        return "cancel"

class SettingsForm(Form):
    def __init__(self, current_settings, version=None):
        self.Text = "CODESYS Sync Settings"
        self.Size = Size(440, 550)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.profile_labels = current_settings.get("available_profile_labels", {})
        self.profile_descriptions = current_settings.get("available_profile_descriptions", {})
        self.user_profiles = set(current_settings.get("user_profiles", []))
        
        # Heading
        lbl = Label()
        lbl.Text = "Configure Sync Behavior"
        lbl.Location = Point(20, 20)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 12, FontStyle.Bold)
        self.Controls.Add(lbl)
        
        # Version label (top-right corner)
        if version:
            lbl_version = Label()
            lbl_version.Text = "v" + str(version)
            lbl_version.Location = Point(320, 24)
            lbl_version.AutoSize = True
            lbl_version.Font = Font("Segoe UI", 8)
            lbl_version.ForeColor = Color.Gray
            self.Controls.Add(lbl_version)
        
        # Runtime info
        y = 60
        lbl_detected_version = Label()
        lbl_detected_version.Text = "Detected CODESYS Version:"
        lbl_detected_version.Location = Point(30, y + 3)
        lbl_detected_version.AutoSize = True
        self.Controls.Add(lbl_detected_version)

        self.txt_detected_version = TextBox()
        self.txt_detected_version.Location = Point(210, y)
        self.txt_detected_version.Size = Size(170, 20)
        self.txt_detected_version.Text = current_settings.get("detected_codesys_version", "N/A")
        self.txt_detected_version.ReadOnly = True
        self.Controls.Add(self.txt_detected_version)

        # Group 1: Export Settings
        y += 35
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

        y += 30
        self.chk_save_exp = CheckBox()
        self.chk_save_exp.Text = "Save Project after Export"
        self.chk_save_exp.Location = Point(30, y)
        self.chk_save_exp.Size = Size(350, 24)
        self.chk_save_exp.Checked = current_settings.get("save_after_export", True)
        self.Controls.Add(self.chk_save_exp)

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

        # Subsection: Backup Retention
        y += 30
        lbl_retention = Label()
        lbl_retention.Text = "Max Backups to Keep (Optional):"
        lbl_retention.Location = Point(50, y+3)
        lbl_retention.AutoSize = True
        self.Controls.Add(lbl_retention)
        
        self.txt_retention = TextBox()
        self.txt_retention.Location = Point(250, y)
        self.txt_retention.Size = Size(60, 20)
        self.txt_retention.Text = str(current_settings.get("retention_count", 10))
        self.Controls.Add(self.txt_retention)

        # Group 3: Logging
        y += 40
        self.chk_logging = CheckBox()
        self.chk_logging.Text = "Enable *.log Files (sync_debug.log, compare.log)"
        self.chk_logging.Location = Point(30, y)
        self.chk_logging.Size = Size(350, 24)
        self.chk_logging.Checked = current_settings.get("enable_logging", False)
        self.Controls.Add(self.chk_logging)

        y += 35
        lbl_profile = Label()
        lbl_profile.Text = "Type Profile:"
        lbl_profile.Location = Point(30, y + 3)
        lbl_profile.AutoSize = True
        self.Controls.Add(lbl_profile)

        self.cmb_profile = ComboBox()
        self.cmb_profile.Location = Point(140, y)
        self.cmb_profile.Size = Size(210, 21)
        for profile_name in current_settings.get("available_profiles", []):
            display_name = profile_name
            if profile_name in self.user_profiles:
                display_name = profile_name + " [user]"
            self.cmb_profile.Items.Add(display_name)
        selected_profile = current_settings.get("type_profile", "")
        if selected_profile:
            if selected_profile in self.user_profiles:
                self.cmb_profile.Text = selected_profile + " [user]"
            else:
                self.cmb_profile.Text = selected_profile
        self.Controls.Add(self.cmb_profile)

        y += 28
        self.lbl_profile_info = Label()
        self.lbl_profile_info.Location = Point(30, y)
        self.lbl_profile_info.Size = Size(380, 48)
        self.lbl_profile_info.ForeColor = Color.DimGray
        self.Controls.Add(self.lbl_profile_info)
        self.cmb_profile.SelectedIndexChanged += self.OnProfileChanged
        self.cmb_profile.TextChanged += self.OnProfileChanged
        self._update_profile_info()

        profiles_dir = current_settings.get("profiles_dir", "")
        if profiles_dir:
            y += 50
            lbl_profiles_dir = Label()
            lbl_profiles_dir.Text = "Profiles dir: " + profiles_dir
            lbl_profiles_dir.Location = Point(30, y)
            lbl_profiles_dir.Size = Size(380, 18)
            lbl_profiles_dir.Font = Font("Segoe UI", 7)
            lbl_profiles_dir.ForeColor = Color.LightGray
            self.Controls.Add(lbl_profiles_dir)

        # Buttons
        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.DialogResult = DialogResult.Cancel
        btn_cancel.Location = Point(300, 440)
        self.Controls.Add(btn_cancel)

        btn_save = Button()
        btn_save.Text = "Save Settings"
        btn_save.DialogResult = DialogResult.OK
        btn_save.Location = Point(170, 440)
        btn_save.Size = Size(120, 23)
        self.Controls.Add(btn_save)
        self.AcceptButton = btn_save
        self.CancelButton = btn_cancel

    def _update_profile_info(self):
        raw_text = self.cmb_profile.Text.strip()
        profile_name = raw_text.replace(" [user]", "")
        profile_label = self.profile_labels.get(profile_name, "")
        desc = self.profile_descriptions.get(profile_name, "")
        parts = []
        if profile_label:
            parts.append(profile_label)
        if profile_name in self.user_profiles:
            parts.append("(user profile)")
        if desc:
            parts.append(desc)
        if parts:
            self.lbl_profile_info.Text = "  ".join(parts)
        else:
            self.lbl_profile_info.Text = "Unknown profile name"

    def OnProfileChanged(self, sender, event):
        self._update_profile_info()

    def get_results(self):
        try:
            retention = int(self.txt_retention.Text.strip())
            if retention < 1:
                retention = 10
        except:
            retention = 10
        
        return {
            "export_xml": self.chk_xml.Checked,
            "backup_binary": self.chk_bin.Checked,
            "backup_name": self.txt_backup_name.Text.strip(),
            "save_after_import": self.chk_save.Checked,
            "save_after_export": self.chk_save_exp.Checked,
            "safety_backup": self.chk_safety.Checked,
            "retention_count": retention,
            "enable_logging": self.chk_logging.Checked,
            "type_profile": self.cmb_profile.Text.strip().replace(" [user]", "")
        }

def show_settings_dialog(current_settings, version=None):
    try:
        form = SettingsForm(current_settings, version)
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
    
    def __init__(self, different, new_in_ide, new_on_disk, unchanged_count, moved=None):
        self.Text = "cds-text-sync: Comparison Results"
        self.Size = Size(500, 480)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.result_action = self.CLOSE
        self.checkboxes = []
        
        # Main Layout: 
        # [Header]
        # [Scrollable Panel for List]
        # [Summary + Selection + Action Buttons]
        
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
        
        # Scrollable Panel
        list_panel = Panel()
        list_panel.Location = Point(0, y)
        list_panel.Size = Size(495, 280) # Fixed height for scrollable area
        list_panel.AutoScroll = True
        # list_panel.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(list_panel)
        self.list_panel = list_panel
        
        inner_y = 5
        # Add sections to inner panel
        if different:
            inner_y = self._add_section(inner_y, "Modified (IDE and Disk differ):", different, "different")
        if new_in_ide:
            inner_y = self._add_section(inner_y, "Missing on Disk (DELETE from IDE?):", new_in_ide, "new")
        if new_on_disk:
            # Map path/file_path to consistent structure for display
            mapped_new = []
            for item in new_on_disk:
                mapped_new.append({
                    "name": item["name"], "path": item["path"], "type": "new file",
                    "file_path": item["file_path"]
                })
            inner_y = self._add_section(inner_y, "New on Disk (need Import):", mapped_new, "new_on_disk")
        
        if moved:
            # Moved items have a special two-line layout
            mapped_moved = []
            for item in moved:
                mapped_moved.append({
                    "name": item["name"],
                    "path": item["ide_path"],
                    "type": "~moved",
                    "type_guid": item.get("type_guid", ""),
                    "obj": item.get("obj"),
                    "file_path": item.get("file_path", ""),
                    "ide_path": item["ide_path"],
                    "disk_path": item["disk_path"],
                    "is_moved": True
                })
            inner_y = self._add_moved_section(inner_y, mapped_moved)
        
        y += list_panel.Height + 10
        
        # Summary
        lbl_sum = Label()
        moved_count = len(moved) if moved else 0
        lbl_sum.Text = "M:" + str(len(different)) + "  +:" + str(len(new_in_ide)) + "  *:" + str(len(new_on_disk or [])) + "  ~:" + str(moved_count) + "  =:" + str(unchanged_count)
        lbl_sum.Location = Point(15, y)
        lbl_sum.AutoSize = True
        self.Controls.Add(lbl_sum)
        y += 25
        
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
    
    def _add_moved_section(self, y, items):
        """Add the Moved/Renamed section with path sub-labels"""
        lbl = Label()
        lbl.Text = "Moved/Renamed (path mismatch):"
        lbl.Location = Point(15, y)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.list_panel.Controls.Add(lbl)
        y += 22
        
        for item in items:
            cb = CheckBox()
            cb.Text = item["name"] + "  [~moved]"
            cb.Location = Point(30, y)
            cb.Size = Size(420, 20)
            cb.Checked = True
            cb.Tag = (item, "moved")
            self.list_panel.Controls.Add(cb)
            self.checkboxes.append(cb)
            y += 20
            
            # Path sub-label: IDE path -> Disk path
            path_lbl = Label()
            path_lbl.Text = "IDE: " + item.get("ide_path", "") + "  ->  Disk: " + item.get("disk_path", "")
            path_lbl.Location = Point(48, y)
            path_lbl.AutoSize = True
            path_lbl.Font = Font("Segoe UI", 7)
            path_lbl.ForeColor = Color.Gray
            self.list_panel.Controls.Add(path_lbl)
            y += 18
        
        y += 8
        return y
    
    def _add_section(self, y, title, items, direction):
        """Add a labeled section with checkboxes and optional diff buttons"""
        lbl = Label()
        lbl.Text = title
        lbl.Location = Point(15, y)
        lbl.AutoSize = True
        lbl.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.list_panel.Controls.Add(lbl)
        y += 22
        
        for item in items:
            cb = CheckBox()
            cb.Text = item["name"] + "  [" + item["type"] + "]"
            cb.Location = Point(30, y)
            cb.Size = Size(350, 20)
            cb.Checked = True
            cb.Tag = (item, direction)
            self.list_panel.Controls.Add(cb)
            self.checkboxes.append(cb)
            
            # Add Diff button if both contents are available
            has_ide = item.get("ide_content", "")
            has_disk = item.get("disk_content", "")
            if has_ide or has_disk:
                btn_diff = Button()
                btn_diff.Text = "Diff"
                btn_diff.Location = Point(390, y - 1)
                btn_diff.Size = Size(48, 21)
                btn_diff.Tag = item
                btn_diff.Click += self._on_diff_click
                btn_diff.Font = Font("Segoe UI", 7)
                self.list_panel.Controls.Add(btn_diff)
            
            y += 22
        
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


def show_compare_dialog(different, new_in_ide, new_on_disk, unchanged_count, moved=None):
    """Show the comparison results dialog. Returns (action, selected_items)"""
    try:
        form = CompareResultsForm(different, new_in_ide, new_on_disk, unchanged_count, moved)
        result = form.ShowDialog()
        if result == DialogResult.OK:
            return form.result_action, form.get_selected()
    except Exception as e:
        print("Error showing compare dialog: " + str(e))
    return CompareResultsForm.CLOSE, []


class DirectoryChoiceForm(Form):
    """Modern choice dialog for setting the sync directory"""
    def __init__(self, title, message):
        self.Text = title
        self.Size = Size(450, 270) # Increased height for better padding
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.choice = "cancel"

        # Main Text
        lbl_msg = Label()
        lbl_msg.Text = "Sync Directory Setup"
        lbl_msg.Font = Font("Segoe UI", 14, FontStyle.Bold)
        lbl_msg.Location = Point(20, 20)
        lbl_msg.AutoSize = True
        lbl_msg.ForeColor = Color.FromArgb(50, 50, 50)
        self.Controls.Add(lbl_msg)

        lbl_sub = Label()
        lbl_sub.Text = "Choose how you would like to configure the primary sync folder."
        lbl_sub.Font = Font("Segoe UI", 9)
        lbl_sub.Location = Point(22, 50)
        lbl_sub.AutoSize = True
        lbl_sub.ForeColor = Color.Gray
        self.Controls.Add(lbl_sub)

        # Buttons - Big and Modern (Removed emojis for better compatibility)
        btn_browse = Button()
        btn_browse.Text = "  Browse Folder...\n  (Select via file explorer)"
        btn_browse.Font = Font("Segoe UI", 10)
        btn_browse.TextAlign = ContentAlignment.MiddleLeft
        btn_browse.Location = Point(25, 90)
        btn_browse.Size = Size(385, 55)
        btn_browse.BackColor = Color.White
        btn_browse.FlatStyle = FlatStyle.Flat
        btn_browse.FlatAppearance.BorderColor = Color.LightGray
        btn_browse.Click += self._on_browse
        self.Controls.Add(btn_browse)

        btn_manual = Button()
        btn_manual.Text = "  Enter Manually...\n  (Use relative ./ paths or text input)"
        btn_manual.Font = Font("Segoe UI", 10)
        btn_manual.TextAlign = ContentAlignment.MiddleLeft
        btn_manual.Location = Point(25, 155)
        btn_manual.Size = Size(385, 55)
        btn_manual.BackColor = Color.White
        btn_manual.FlatStyle = FlatStyle.Flat
        btn_manual.FlatAppearance.BorderColor = Color.LightGray
        btn_manual.Click += self._on_manual
        self.Controls.Add(btn_manual)

    def _on_browse(self, sender, event):
        self.choice = "yes"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_manual(self, sender, event):
        self.choice = "no"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_cancel(self, sender, event):
        self.choice = "cancel"
        self.DialogResult = DialogResult.Cancel
        self.Close()

def show_directory_choice_dialog(title, message):
    try:
        form = DirectoryChoiceForm(title, message)
        form.ShowDialog()
        return form.choice
    except:
        # Fallback to standard if custom fails
        from codesys_ui import ask_yes_no_cancel
        return ask_yes_no_cancel(title, message)

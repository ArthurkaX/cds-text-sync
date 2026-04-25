# -*- coding: utf-8 -*-
"""
codesys_ui.py - Modern UI components for CODESYS scripts
"""
import clr
import os
import textwrap
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Application, Form, Label, CheckBox, Button, FormBorderStyle,
        DialogResult, FormStartPosition, NotifyIcon, ToolTipIcon, TextBox,
        Control, Keys, Panel, RichTextBoxScrollBars, BorderStyle, ComboBox,
        MessageBox, MessageBoxButtons, MessageBoxIcon, FlatStyle, GroupBox, ToolTip
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
        self.Size = Size(530, 470)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.tooltip = ToolTip()
        self.tooltip.AutomaticDelay = 1200
        self.tooltip.AutoPopDelay = 18000
        self.tooltip.InitialDelay = 1200
        self.tooltip.ReshowDelay = 400
        self.tooltip.IsBalloon = False
        self.tooltip.UseAnimation = True
        self.tooltip.UseFading = True
        self.tooltip.ShowAlways = True
        self.profile_labels = current_settings.get("available_profile_labels", {})
        self.profile_descriptions = current_settings.get("available_profile_descriptions", {})
        self.user_profiles = set(current_settings.get("user_profiles", []))

        def format_tip(text, width=48):
            lines = []
            for paragraph in str(text).split("\n"):
                chunk = paragraph.strip()
                if not chunk:
                    lines.append("")
                else:
                    lines.extend(textwrap.wrap(chunk, width=width))
            return "\n".join(lines)

        def set_tip(control, text):
            if text:
                self.tooltip.SetToolTip(control, format_tip(text))

        # Heading
        lbl_heading = Label()
        lbl_heading.Text = "Configure Sync Behavior"
        lbl_heading.Location = Point(20, 15)
        lbl_heading.AutoSize = True
        lbl_heading.Font = Font("Segoe UI", 12, FontStyle.Bold)
        self.Controls.Add(lbl_heading)

        # Version label (top-right corner)
        if version:
            lbl_version = Label()
            lbl_version.Text = "v" + str(version)
            lbl_version.Location = Point(410, 18)
            lbl_version.AutoSize = True
            lbl_version.Font = Font("Segoe UI", 8)
            lbl_version.ForeColor = Color.Gray
            self.Controls.Add(lbl_version)

        # Runtime info (outside groups)
        lbl_detected_version = Label()
        lbl_detected_version.Text = "Detected CODESYS Version:"
        lbl_detected_version.Location = Point(20, 50)
        lbl_detected_version.AutoSize = True
        set_tip(
            lbl_detected_version,
            "Shows the CODESYS runtime/version detected from the current session. "
            "This value is read-only and is only meant to help you confirm which IDE build the script is running against."
        )
        self.Controls.Add(lbl_detected_version)

        self.txt_detected_version = TextBox()
        self.txt_detected_version.Location = Point(180, 47)
        self.txt_detected_version.Size = Size(140, 20)
        self.txt_detected_version.Text = current_settings.get("detected_codesys_version", "N/A")
        self.txt_detected_version.ReadOnly = True
        set_tip(
            self.txt_detected_version,
            "Read-only version field populated by the script. "
            "Use it to verify the detected CODESYS version before changing any project sync options."
        )
        self.Controls.Add(self.txt_detected_version)

        # Group A: Sync & Export (left side)
        grp_sync = GroupBox()
        grp_sync.Text = "Sync Configuration"
        grp_sync.Location = Point(20, 80)
        grp_sync.Size = Size(240, 175)
        set_tip(
            grp_sync,
            "Controls how the project is exported and synchronized with disk. "
            "These options affect whether text-based source files, logs, and other sync artifacts are produced."
        )
        self.Controls.Add(grp_sync)

        # Type Profile (in Sync group)
        y_sync = 20
        lbl_profile = Label()
        lbl_profile.Text = "Type Profile:"
        lbl_profile.Location = Point(10, y_sync)
        lbl_profile.AutoSize = True
        set_tip(
            lbl_profile,
            "Selects the type profile that maps CODESYS object types to export/import behavior. "
            "The chosen profile determines how the script interprets projects, folders, and special object categories."
        )
        grp_sync.Controls.Add(lbl_profile)

        self.cmb_profile = ComboBox()
        self.cmb_profile.Location = Point(10, y_sync + 20)
        self.cmb_profile.Size = Size(195, 21)
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
        grp_sync.Controls.Add(self.cmb_profile)
        set_tip(
            self.cmb_profile,
            "Choose which type profile to use for this project. "
            "Built-in profiles are provided by the script; user profiles come from the local profiles directory. "
            "The tooltip updates to show the selected profile label and description."
        )

        # Profile info (no tooltip)
        profile_label = self.profile_labels.get(selected_profile, "")
        profile_desc = self.profile_descriptions.get(selected_profile, "")
        if profile_label or profile_desc:
            info_text = profile_label
            if profile_desc:
                info_text += " - " + profile_desc
            if profile_name in self.user_profiles:
                info_text += " [user]"
            self.cmb_profile.DropDownWidth = 200

        # Export Native XML
        y_sync += 55
        self.chk_xml = CheckBox()
        self.chk_xml.Text = "Export Native XML"
        self.chk_xml.Location = Point(10, y_sync)
        self.chk_xml.Size = Size(200, 24)
        self.chk_xml.Checked = current_settings.get("export_xml", False)
        set_tip(
            self.chk_xml,
            "When enabled, the script exports non-textual project objects such as visualizations, alarms, image pools, and text lists to a companion XML folder. "
            "Use this if you want broader diff coverage beyond Structured Text files."
        )
        grp_sync.Controls.Add(self.chk_xml)

        # Enable .log Files
        y_sync += 30
        self.chk_logging = CheckBox()
        self.chk_logging.Text = "Enable *.log Files"
        self.chk_logging.Location = Point(10, y_sync)
        self.chk_logging.Size = Size(200, 24)
        self.chk_logging.Checked = current_settings.get("enable_logging", False)
        set_tip(
            self.chk_logging,
            "When enabled, the script writes additional log files during export and import operations. "
            "This is useful for troubleshooting, auditing sync runs, and reviewing the exact actions taken by the engine."
        )
        grp_sync.Controls.Add(self.chk_logging)

        # Group B: Backup & Safety (right side)
        grp_backup = GroupBox()
        grp_backup.Text = "Automation & Backups"
        grp_backup.Location = Point(270, 80)
        grp_backup.Size = Size(240, 205)
        set_tip(
            grp_backup,
            "Controls automated project backups and import/export convenience settings. "
            "These options determine whether the script saves the project, creates binary backups, and preserves timestamped recovery copies."
        )
        self.Controls.Add(grp_backup)

        y_backup = 20
        self.chk_bin = CheckBox()
        self.chk_bin.Text = "Backup .project Binary"
        self.chk_bin.Location = Point(10, y_backup)
        self.chk_bin.Size = Size(200, 24)
        self.chk_bin.Checked = current_settings.get("backup_binary", False)
        set_tip(
            self.chk_bin,
            "When enabled, the script keeps a binary copy of the active CODESYS project file in the backup folder. "
            "This is especially useful for Git LFS or for preserving a restorable binary snapshot alongside the text export."
        )
        grp_backup.Controls.Add(self.chk_bin)

        y_backup += 35
        lbl_name = Label()
        lbl_name.Text = "Backup Name:"
        lbl_name.Location = Point(10, y_backup)
        lbl_name.AutoSize = True
        set_tip(
            lbl_name,
            "Defines the fixed base name used for the binary backup file. "
            "Set this if you want the backup filename to remain stable even when the project is renamed."
        )
        grp_backup.Controls.Add(lbl_name)

        self.txt_backup_name = TextBox()
        self.txt_backup_name.Location = Point(10, y_backup + 20)
        self.txt_backup_name.Size = Size(200, 20)
        self.txt_backup_name.Text = current_settings.get("backup_name", "")
        set_tip(
            self.txt_backup_name,
            "Enter the fixed filename stem for the binary backup copy. "
            "If left blank, the script uses the current project naming behavior instead of forcing a custom backup name."
        )
        grp_backup.Controls.Add(self.txt_backup_name)

        y_backup += 50
        self.chk_safety = CheckBox()
        self.chk_safety.Text = "Timestamped Backup"
        self.chk_safety.Location = Point(10, y_backup)
        self.chk_safety.Size = Size(200, 24)
        self.chk_safety.Checked = current_settings.get("safety_backup", True)
        set_tip(
            self.chk_safety,
            "When enabled, the script creates a unique timestamped backup before import operations. "
            "This protects you from accidental overwrites and gives you a rollback point for risky changes."
        )
        grp_backup.Controls.Add(self.chk_safety)

        y_backup += 30
        self.chk_save = CheckBox()
        self.chk_save.Text = "Save (Import)"
        self.chk_save.Location = Point(10, y_backup)
        self.chk_save.Size = Size(100, 24)
        self.chk_save.Checked = current_settings.get("save_after_import", True)
        set_tip(
            self.chk_save,
            "When enabled, the project is saved automatically after a successful import. "
            "This helps keep the IDE state and the exported disk state aligned without requiring a manual save."
        )
        grp_backup.Controls.Add(self.chk_save)

        self.chk_save_exp = CheckBox()
        self.chk_save_exp.Text = "Save (Export)"
        self.chk_save_exp.Location = Point(120, y_backup)
        self.chk_save_exp.Size = Size(100, 24)
        self.chk_save_exp.Checked = current_settings.get("save_after_export", True)
        set_tip(
            self.chk_save_exp,
            "When enabled, the project is saved automatically after a successful export. "
            "This is useful when you want the latest IDE changes written to disk immediately after synchronization."
        )
        grp_backup.Controls.Add(self.chk_save_exp)

        y_backup += 32
        lbl_retention = Label()
        lbl_retention.Text = "Backup Retention:"
        lbl_retention.Location = Point(10, y_backup)
        lbl_retention.AutoSize = True
        set_tip(
            lbl_retention,
            "Sets how many timestamped safety backups are kept before older ones are removed. "
            "Higher values provide more rollback history, while lower values keep the backup folder smaller."
        )
        grp_backup.Controls.Add(lbl_retention)

        self.txt_retention = TextBox()
        self.txt_retention.Location = Point(140, y_backup - 3)
        self.txt_retention.Size = Size(50, 20)
        self.txt_retention.Text = str(current_settings.get("retention_count", 10))
        set_tip(
            self.txt_retention,
            "Enter the maximum number of timestamped backups to keep. "
            "The script will preserve this many recent backups and prune older ones during cleanup."
        )
        grp_backup.Controls.Add(self.txt_retention)

        # Separator line above buttons
        lbl_separator = Label()
        lbl_separator.Text = ""
        lbl_separator.Location = Point(20, 305)
        lbl_separator.Size = Size(490, 2)
        lbl_separator.BorderStyle = BorderStyle.Fixed3D
        lbl_separator.BackColor = Color.LightGray
        self.Controls.Add(lbl_separator)

        # Profiles directory path (status bar style - bottom left)
        profiles_dir = current_settings.get("profiles_dir", "")
        if profiles_dir:
            lbl_profiles_dir = Label()
            lbl_profiles_dir.Text = "Profiles: " + profiles_dir
            lbl_profiles_dir.Location = Point(20, 320)
            lbl_profiles_dir.AutoSize = True
            lbl_profiles_dir.Font = Font("Segoe UI", 8)
            lbl_profiles_dir.ForeColor = Color.FromArgb(85, 85, 85)
            set_tip(
                lbl_profiles_dir,
                "Shows the directory where user-defined type profiles are stored. "
                "Add or edit profile JSON files here if you want custom export/import behavior."
            )
            self.Controls.Add(lbl_profiles_dir)

        # Buttons (bottom right)
        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.DialogResult = DialogResult.Cancel
        btn_cancel.Location = Point(350, 400)
        btn_cancel.Size = Size(75, 23)
        set_tip(
            btn_cancel,
            "Close the dialog without applying any changes. "
            "All current selections are discarded if you cancel."
        )
        self.Controls.Add(btn_cancel)

        btn_save = Button()
        btn_save.Text = "Save"
        btn_save.DialogResult = DialogResult.OK
        btn_save.Location = Point(435, 400)
        btn_save.Size = Size(75, 23)
        set_tip(
            btn_save,
            "Save the selected configuration options back into the project properties. "
            "Only press this when you are ready to apply the settings for the current project."
        )
        self.Controls.Add(btn_save)
        self.AcceptButton = btn_save
        self.CancelButton = btn_cancel

    def _update_profile_info(self):
        raw_text = self.cmb_profile.Text.strip()
        profile_name = raw_text.replace(" [user]", "")
        profile_label = self.profile_labels.get(profile_name, "")
        profile_desc = self.profile_descriptions.get(profile_name, "")
        if profile_label or profile_desc:
            tooltip_text = "Label: " + profile_label
            if profile_desc:
                tooltip_text += "\n\n" + profile_desc
            if profile_name in self.user_profiles:
                tooltip_text += "\n\n(user profile)"
            self.tooltip.SetToolTip(self.cmb_profile, tooltip_text)
        else:
            self.tooltip.SetToolTip(self.cmb_profile, "Unknown profile name")

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
    
    def _format_tip(self, text, width=48):
        lines = []
        for paragraph in str(text).split("\n"):
            chunk = paragraph.strip()
            if not chunk:
                lines.append("")
            else:
                lines.extend(textwrap.wrap(chunk, width=width))
        return "\n".join(lines)

    def _set_tip(self, control, text):
        if text:
            self.tooltip.SetToolTip(control, self._format_tip(text))
    
    def __init__(self, different, new_in_ide, new_on_disk, unchanged_count, moved=None):
        self.Text = "cds-text-sync: Comparison Results"
        self.Size = Size(500, 480)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.result_action = self.CLOSE
        self.checkboxes = []
        self.tooltip = ToolTip()
        self.tooltip.AutomaticDelay = 1200
        self.tooltip.AutoPopDelay = 18000
        self.tooltip.InitialDelay = 1200
        self.tooltip.ReshowDelay = 400
        self.tooltip.IsBalloon = False
        self.tooltip.UseAnimation = True
        self.tooltip.UseFading = True
        self.tooltip.ShowAlways = True
        
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
        self._set_tip(
            lbl,
            "This dialog lists all objects that differ between the IDE project and the files on disk. "
            "Use the checkboxes to choose which items should be synchronized."
        )
        self.Controls.Add(lbl)
        y += 30
        
        lbl2 = Label()
        lbl2.Text = "Select the objects you want to synchronize:"
        lbl2.Location = Point(15, y)
        lbl2.AutoSize = True
        self._set_tip(
            lbl2,
            "Select only the items you want to move between the IDE and disk. "
            "Unchecked items will be left unchanged when you run Import or Export."
        )
        self.Controls.Add(lbl2)
        y += 28
        
        # Scrollable Panel
        list_panel = Panel()
        list_panel.Location = Point(0, y)
        list_panel.Size = Size(495, 280) # Fixed height for scrollable area
        list_panel.AutoScroll = True
        # list_panel.BorderStyle = BorderStyle.FixedSingle
        self._set_tip(
            list_panel,
            "Scrollable list of detected differences. "
            "Each row represents an object that can be imported, exported, or compared in detail."
        )
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
        self._set_tip(
            lbl_sum,
            "Summary counts for the current comparison run. "
            "M = modified, + = missing on disk, * = new on disk, ~ = moved or renamed, = = unchanged."
        )
        self.Controls.Add(lbl_sum)
        y += 25
        
        # Select All / None
        btn_all = Button()
        btn_all.Text = "All"
        btn_all.Location = Point(15, y)
        btn_all.Size = Size(55, 25)
        btn_all.Click += self._select_all
        self._set_tip(
            btn_all,
            "Select every item in the list. "
            "Use this when you want all detected differences to be included in the next sync action."
        )
        self.Controls.Add(btn_all)
        
        btn_none = Button()
        btn_none.Text = "None"
        btn_none.Location = Point(75, y)
        btn_none.Size = Size(55, 25)
        btn_none.Click += self._select_none
        self._set_tip(
            btn_none,
            "Clear all selections in the list. "
            "Use this when you want to manually choose only a few objects to synchronize."
        )
        self.Controls.Add(btn_none)
        
        # Action buttons
        btn_close = Button()
        btn_close.Text = "Close"
        btn_close.Location = Point(380, y)
        btn_close.Size = Size(90, 28)
        btn_close.DialogResult = DialogResult.Cancel
        self._set_tip(
            btn_close,
            "Close this dialog without starting import or export. "
            "No synchronization action is performed when you close the window."
        )
        self.Controls.Add(btn_close)
        self.CancelButton = btn_close
        
        btn_export = Button()
        btn_export.Text = "Export to Disk"
        btn_export.Location = Point(260, y)
        btn_export.Size = Size(110, 28)
        btn_export.Click += self._on_export
        self._set_tip(
            btn_export,
            "Export the selected IDE objects to disk. "
            "This pushes the chosen changes from the CODESYS project into the filesystem representation."
        )
        self.Controls.Add(btn_export)
        
        btn_import = Button()
        btn_import.Text = "Import to IDE"
        btn_import.Location = Point(140, y)
        btn_import.Size = Size(110, 28)
        btn_import.Click += self._on_import
        self._set_tip(
            btn_import,
            "Import the selected disk files into the IDE project. "
            "This applies the chosen file changes back into CODESYS."
        )
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
        self._set_tip(
            lbl,
            "These items exist on both sides but their paths do not match. "
            "Treat them as renamed or moved objects rather than deleted and recreated items."
        )
        self.list_panel.Controls.Add(lbl)
        y += 22
        
        for item in items:
            cb = CheckBox()
            cb.Text = item["name"] + "  [~moved]"
            cb.Location = Point(30, y)
            cb.Size = Size(420, 20)
            cb.Checked = True
            cb.Tag = (item, "moved")
            self._set_tip(
                cb,
                "Moved or renamed object. "
                "It is present in both IDE and disk, but the paths differ, so synchronization should preserve the object identity."
            )
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
            self._set_tip(
                path_lbl,
                "Shows the old IDE path and the current disk path for this moved or renamed object. "
                "Use this information to confirm that the path change is intentional."
            )
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
        if direction == "different":
            section_tip = "Objects whose content differs between IDE and disk. "
            section_tip += "Use Diff to inspect the changes before importing or exporting."
        elif direction == "new":
            section_tip = "Objects that exist in the IDE but not on disk. "
            section_tip += "Exporting will write them to files, while importing may remove them from the IDE."
        else:
            section_tip = "Objects that exist on disk but are missing in the IDE. "
            section_tip += "Importing will create or update them inside the project."
        self._set_tip(lbl, section_tip)
        self.list_panel.Controls.Add(lbl)
        y += 22
        
        for item in items:
            cb = CheckBox()
            cb.Text = item["name"] + "  [" + item["type"] + "]"
            cb.Location = Point(30, y)
            cb.Size = Size(350, 20)
            cb.Checked = True
            cb.Tag = (item, direction)
            tooltip_text = "Name: " + item.get("name", "") + "\nType: " + item.get("type", "")
            path_value = item.get("path", "")
            if path_value:
                tooltip_text += "\nPath: " + path_value
            if item.get("file_path", ""):
                tooltip_text += "\nDisk file: " + item.get("file_path", "")
            self._set_tip(
                cb,
                tooltip_text + "\n\nCheck this item to include it in the next synchronization step."
            )
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
                self._set_tip(
                    btn_diff,
                    "Open a side-by-side diff for this item. "
                    "Hold Ctrl while clicking to save both versions into the .diff folder instead."
                )
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

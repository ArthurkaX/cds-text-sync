# -*- coding: utf-8 -*-
"""
codesys_ui.py - Modern UI components for CODESYS scripts
"""
import clr
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Application, Form, Label, CheckBox, Button, FormBorderStyle, 
        DialogResult, FormStartPosition, NotifyIcon, ToolTipIcon, TextBox
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

# -*- coding: utf-8 -*-
"""
ide_daemon_ui.py — WinForms UI for the CODESYS reverse-pipe daemon.

Shows inside CODESYS while Project_daemon.py runs.
Has a command log listbox, log tools, Stop button, and Settings button
that opens a security/config window.
"""

from __future__ import print_function
import sys
import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Windows.Forms import (
    Form, Button, ListBox, DockStyle, Padding, FlatStyle,
    Application, FormStartPosition, FormBorderStyle,
    Label, TrackBar, CheckedListBox, Panel,
    BorderStyle, MessageBox, MessageBoxButtons,
    MessageBoxIcon, DialogResult, TabControl, TabPage,
    AnchorStyles, Clipboard, ToolTip,
)
from System.Drawing import (
    Point, Size, Font, FontStyle, Color, ContentAlignment
)


# ── Settings Form ──────────────────────────────────────────────────────────

class SettingsForm(Form):
    """Settings window for daemon config (poll frequency + permissions)."""

    def __init__(self):
        self.Text = "Daemon Settings"
        self.Width = 480
        self.Height = 420
        self.MinimumSize = Size(400, 350)
        self.StartPosition = FormStartPosition.CenterParent
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        self._config = self._load_config()
        self._changed = False

        self._build_ui()

    def _load_config(self):
        """Load config from the daemon's storage."""
        try:
            from ide_daemon_state import _load_daemon_config
            return _load_daemon_config()
        except Exception:
            return {"poll_ms": 200, "deny": []}

    def _save_config(self, config):
        """Save config to the daemon's storage."""
        try:
            from ide_daemon_state import _save_daemon_config
            return _save_daemon_config(config)
        except Exception:
            return False

    def _build_ui(self):
        # Tab control
        self.tab_control = TabControl()
        self.tab_control.Dock = DockStyle.Fill

        # Tab 1: Poll frequency
        tab_poll = TabPage()
        tab_poll.Text = "General"
        self._build_poll_tab(tab_poll)
        self.tab_control.Controls.Add(tab_poll)

        # Tab 2: Permissions
        tab_perm = TabPage()
        tab_perm.Text = "Permissions"
        self._build_perm_tab(tab_perm)
        self.tab_control.Controls.Add(tab_perm)

        self.Controls.Add(self.tab_control)

        # Bottom buttons
        bottom_panel = Panel()
        bottom_panel.Dock = DockStyle.Bottom
        bottom_panel.Height = 40
        bottom_panel.Padding = Padding(8, 6, 8, 6)

        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Width = 80
        btn_cancel.Height = 28
        btn_cancel.DialogResult = DialogResult.Cancel
        btn_cancel.Anchor = AnchorStyles.Right | AnchorStyles.Bottom
        btn_cancel.Click += self._on_cancel

        btn_apply = Button()
        btn_apply.Text = "Apply"
        btn_apply.Width = 80
        btn_apply.Height = 28
        btn_apply.Anchor = AnchorStyles.Right | AnchorStyles.Bottom
        btn_apply.Click += self._on_apply

        btn_ok = Button()
        btn_ok.Text = "OK"
        btn_ok.Width = 80
        btn_ok.Height = 28
        btn_ok.Anchor = AnchorStyles.Right | AnchorStyles.Bottom
        btn_ok.Click += self._on_ok

        # Arrange buttons right-to-left
        btn_ok.Location = Point(bottom_panel.Width - 88, 6)
        btn_apply.Location = Point(bottom_panel.Width - 176, 6)
        btn_cancel.Location = Point(bottom_panel.Width - 264, 6)

        bottom_panel.Controls.Add(btn_ok)
        bottom_panel.Controls.Add(btn_apply)
        bottom_panel.Controls.Add(btn_cancel)
        self.Controls.Add(bottom_panel)

    def _build_poll_tab(self, tab):
        tab.Padding = Padding(12, 12, 12, 12)

        lbl_poll = Label()
        lbl_poll.Text = "Reverse pipe poll interval (ms):"
        lbl_poll.Location = Point(12, 12)
        lbl_poll.Size = Size(200, 20)

        poll_val = self._config.get("poll_ms", 200)
        self.lbl_poll_val = Label()
        self.lbl_poll_val.Text = str(poll_val) + " ms"
        self.lbl_poll_val.Location = Point(320, 12)
        self.lbl_poll_val.Size = Size(80, 20)
        self.lbl_poll_val.TextAlign = ContentAlignment.MiddleRight

        self.track_poll = TrackBar()
        self.track_poll.Minimum = 10
        self.track_poll.Maximum = 10000
        self.track_poll.Value = max(10, min(10000, poll_val))
        self.track_poll.TickFrequency = 500
        self.track_poll.LargeChange = 500
        self.track_poll.SmallChange = 50
        self.track_poll.Location = Point(12, 40)
        self.track_poll.Size = Size(420, 40)
        self.track_poll.ValueChanged += self._on_poll_changed

        lbl_range = Label()
        lbl_range.Text = "10 ms (fast)                                         10000 ms (slow)"
        lbl_range.Location = Point(12, 80)
        lbl_range.Size = Size(420, 16)
        lbl_range.Font = Font("Segoe UI", 7.5, FontStyle.Regular)
        lbl_range.ForeColor = Color.Gray

        lbl_note = Label()
        lbl_note.Text = "Lower = more responsive, higher = less CPU usage."
        lbl_note.Location = Point(12, 105)
        lbl_note.Size = Size(420, 20)
        lbl_note.Font = Font("Segoe UI", 8, FontStyle.Italic)
        lbl_note.ForeColor = Color.Gray

        tab.Controls.Add(lbl_poll)
        tab.Controls.Add(self.lbl_poll_val)
        tab.Controls.Add(self.track_poll)
        tab.Controls.Add(lbl_range)
        tab.Controls.Add(lbl_note)

    def _build_perm_tab(self, tab):
        tab.Padding = Padding(12, 12, 12, 12)

        lbl_info = Label()
        lbl_info.Text = "Check operations to DENY (block):"
        lbl_info.Location = Point(12, 12)
        lbl_info.Size = Size(400, 20)

        self.perm_list = CheckedListBox()
        self.perm_list.Location = Point(12, 36)
        self.perm_list.Size = Size(420, 280)
        self.perm_list.BorderStyle = BorderStyle.FixedSingle
        self.perm_list.CheckOnClick = True

        # All controllable commands
        all_ops = [
            ("reset_plc", "reset_plc — Reset PLC (any kind)"),
            ("reset_plc --kind origin", "reset_plc --origin — ⚠ DANGEROUS: erase app"),
            ("write_variable", "write_variable — Change PLC variable value"),
            ("create_boot_app", "create_boot_app — Write boot app to PLC"),
            ("sync_import", "sync_import — Modify project from .dump/"),
            ("sync_import_text", "sync_import_text — Import from project-view/"),
            ("build", "build — Compile and overwrite build output"),
            ("start_plc", "start_plc — Start PLC runtime"),
            ("stop_plc", "stop_plc — Stop PLC runtime"),
            ("plc_upload", "plc_upload — Upload file to PLC filesystem"),
            ("source_download", "source_download — Write source files to disk"),
            ("delete_pou", "delete_pou — Delete POU/Function/FunctionBlock"),
        ]

        deny_list = self._config.get("deny", [])
        for cmd_key, cmd_label in all_ops:
            idx = self.perm_list.Items.Add(cmd_label, cmd_key in deny_list)
            # Store the key as item data
            self.perm_list.SetItemChecked(idx, cmd_key in deny_list)

        # Store keys for later retrieval
        self._perm_keys = [k for k, _ in all_ops]

        lbl_note = Label()
        lbl_note.Text = "Unchecked = allowed. Checked = blocked (CLI gets 'Forbidden' error)."
        lbl_note.Location = Point(12, 324)
        lbl_note.Size = Size(420, 20)
        lbl_note.Font = Font("Segoe UI", 8, FontStyle.Italic)
        lbl_note.ForeColor = Color.Gray

        tab.Controls.Add(lbl_info)
        tab.Controls.Add(self.perm_list)
        tab.Controls.Add(lbl_note)

    def _on_poll_changed(self, sender, args):
        val = self.track_poll.Value
        # Snap to round numbers for readability
        if val < 100:
            val = max(10, (val // 10) * 10)
        elif val < 1000:
            val = (val // 50) * 50
        else:
            val = (val // 100) * 100
        val = max(10, min(10000, val))
        self.lbl_poll_val.Text = str(val) + " ms"
        self._changed = True

    def _collect_config(self):
        """Read UI values into a config dict."""
        config = {
            "poll_ms": self.track_poll.Value,
            "deny": [],
        }
        # Collect denied operations
        deny_list = []
        for i in range(self.perm_list.Items.Count):
            if self.perm_list.GetItemChecked(i):
                key = self._perm_keys[i] if i < len(self._perm_keys) else ""
                if key:
                    deny_list.append(key)
        config["deny"] = deny_list
        return config

    def _on_apply(self, sender=None, args=None):
        config = self._collect_config()
        ok = self._save_config(config)
        if ok:
            self._config = config
            self._changed = False
            # Update poll interval in daemon loop
            try:
                if hasattr(sys, "_codesys_daemon_loop"):
                    sys._codesys_daemon_loop["config"] = config
            except Exception:
                pass
            MessageBox.Show("Settings saved.", "Daemon Settings",
                          MessageBoxButtons.OK, MessageBoxIcon.Information)
        else:
            MessageBox.Show("Failed to save settings.", "Error",
                          MessageBoxButtons.OK, MessageBoxIcon.Warning)

    def _on_ok(self, sender, args):
        self._on_apply()
        self.Close()

    def _on_cancel(self, sender, args):
        self.Close()


# ── Main Daemon Form ───────────────────────────────────────────────────────

class DaemonForm(Form):
    """Small window shown inside CODESYS while the daemon runs."""

    def __init__(self):
        self.Text = "cds-text-sync Daemon"
        self.Width = 520
        self.Height = 360
        self.MinimumSize = Size(350, 220)
        self.StartPosition = FormStartPosition.Manual
        self.Left = 20
        self.Top = 20
        self.ControlBox = True
        self._stopping = False
        self.FormClosing += self._on_form_closing

        # Command log listbox
        self.log_list = ListBox()
        self.log_list.Dock = DockStyle.Fill
        self.log_list.Font = Font("Consolas", 9.5, FontStyle.Regular)
        self.log_list.BackColor = Color.FromArgb(245, 245, 245)
        self.log_list.HorizontalScrollbar = True
        self.log_list.IntegralHeight = False

        # Buttons
        self.copy_log_btn = Button()
        self.copy_log_btn.Text = u"⎘"
        self.copy_log_btn.Width = 26
        self.copy_log_btn.Height = 24
        self.copy_log_btn.FlatStyle = FlatStyle.System
        self.copy_log_btn.Font = Font("Segoe UI Symbol", 9, FontStyle.Regular)
        self.copy_log_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
        self.copy_log_btn.Click += self._on_copy_log_click

        self.clear_log_btn = Button()
        self.clear_log_btn.Text = u"⌫"
        self.clear_log_btn.Width = 26
        self.clear_log_btn.Height = 24
        self.clear_log_btn.FlatStyle = FlatStyle.System
        self.clear_log_btn.Font = Font("Segoe UI Symbol", 9, FontStyle.Regular)
        self.clear_log_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
        self.clear_log_btn.Click += self._on_clear_log_click

        self.stop_btn = Button()
        self.stop_btn.Text = "Stop Daemon"
        self.stop_btn.Width = 110
        self.stop_btn.Height = 30
        self.stop_btn.FlatStyle = FlatStyle.System
        self.stop_btn.BackColor = Color.FromArgb(255, 220, 220)
        self.stop_btn.Click += self._on_stop_click

        self.run_tests_btn = Button()
        self.run_tests_btn.Text = "Run Tests"
        self.run_tests_btn.Width = 90
        self.run_tests_btn.Height = 30
        self.run_tests_btn.FlatStyle = FlatStyle.System
        self.run_tests_btn.Click += self._on_run_tests_click

        self.settings_btn = Button()
        self.settings_btn.Text = "Settings"
        self.settings_btn.Width = 80
        self.settings_btn.Height = 30
        self.settings_btn.FlatStyle = FlatStyle.System
        self.settings_btn.Click += self._on_settings_click

        # Layout
        self.Controls.Add(self.log_list)
        self._place_log_tool_buttons()
        self.Controls.Add(self.clear_log_btn)
        self.Controls.Add(self.copy_log_btn)
        self.clear_log_btn.BringToFront()
        self.copy_log_btn.BringToFront()

        self._tooltips = ToolTip()
        self._tooltips.SetToolTip(self.copy_log_btn, "Copy full log")
        self._tooltips.SetToolTip(self.clear_log_btn, "Clear log")

        bottom_panel = self._create_bottom_panel()
        self.Controls.Add(bottom_panel)

    def _place_log_tool_buttons(self):
        top = 6
        gap = 4
        right = 8
        self.clear_log_btn.Location = Point(self.ClientSize.Width - right - self.clear_log_btn.Width, top)
        self.copy_log_btn.Location = Point(self.clear_log_btn.Left - gap - self.copy_log_btn.Width, top)

    def _create_bottom_panel(self):
        from System.Windows.Forms import Panel, Label, BorderStyle
        panel = Panel()
        panel.Dock = DockStyle.Bottom
        panel.Height = 36
        panel.BorderStyle = BorderStyle.FixedSingle

        self.status_label = Label()
        self.status_label.Text = "Running | 0 commands"
        self.status_label.Dock = DockStyle.Fill
        self.status_label.TextAlign = ContentAlignment.MiddleLeft
        self.status_label.Padding = Padding(6, 0, 0, 0)

        self.run_tests_btn.Dock = DockStyle.Right
        self.stop_btn.Dock = DockStyle.Right
        self.settings_btn.Dock = DockStyle.Right

        panel.Controls.Add(self.status_label)
        panel.Controls.Add(self.run_tests_btn)
        panel.Controls.Add(self.settings_btn)
        panel.Controls.Add(self.stop_btn)
        return panel

    def log_command(self, method):
        """Add a line to the command log."""
        import time
        ts = time.strftime("%H:%M:%S")
        msg = "[{0}] {1}".format(ts, method)
        self.log_list.Items.Add(msg)
        if self.log_list.Items.Count > 0:
            self.log_list.TopIndex = self.log_list.Items.Count - 1

    def set_command_count(self, count):
        self.status_label.Text = "Running | {0} commands".format(count)

    def _get_log_text(self):
        lines = []
        for i in range(self.log_list.Items.Count):
            lines.append(str(self.log_list.Items[i]))
        return "\r\n".join(lines)

    def _on_copy_log_click(self, sender, args):
        """Copy the full dashboard log to the Windows clipboard."""
        text = self._get_log_text()
        if not text:
            return
        try:
            Clipboard.SetText(text)
        except Exception as e:
            MessageBox.Show("Failed to copy log:\n" + str(e), "Clipboard Error",
                          MessageBoxButtons.OK, MessageBoxIcon.Warning)

    def _on_clear_log_click(self, sender, args):
        """Clear the dashboard command log."""
        self.log_list.Items.Clear()

    def _request_stop(self, source):
        """Request daemon loop shutdown. Safe to call more than once."""
        if self._stopping:
            return
        self._stopping = True
        self.log_command("STOP requested via {0}".format(source))
        try:
            self.status_label.Text = "Stopping..."
        except Exception:
            pass
        if hasattr(sys, "_codesys_daemon_loop"):
            sys._codesys_daemon_loop["running"] = False

    def _on_stop_click(self, sender, args):
        """Handle Stop button click."""
        self._request_stop("UI")

    def _on_form_closing(self, sender, args):
        """Treat the window close button as Stop Daemon."""
        self._request_stop("window close")

    def _on_run_tests_click(self, sender, args):
        """Handle Run Tests button click — execute all tests from .test/."""
        self.log_command("Run tests: all")
        Application.DoEvents()
        try:
            # Execute tests via the daemon's command handler
            from ide_reverse_pipe_loop import _cmd_cicd
            result = _cmd_cicd({"file": ""})
            Application.DoEvents()
            if result.get("ok"):
                data = result["data"]
                summary = data.get("summary", {})
                pass_count = int(summary.get("ok", 0))
                fail_count = int(summary.get("not_ok", 0))

                for item in data.get("files", []):
                    label = item.get("file") or item.get("plan") or "test"
                    item_total = int(item.get("tests_ok", 0)) + int(item.get("tests_failed", 0))
                    item_passed = int(item.get("tests_ok", 0))
                    item_status = "PASS" if item.get("ok") else "FAIL"
                    if item_total > 0:
                        self.log_command("{0} {1} ({2}/{3})".format(item_status, label, item_passed, item_total))
                    else:
                        self.log_command("{0} {1}".format(item_status, label))

                total = int(summary.get("total", pass_count + fail_count))
                if fail_count:
                    msg = "FAIL\n\nPassed: {0}/{1}\nFailed: {2}".format(pass_count, total, fail_count)
                else:
                    msg = "PASS\n\nPassed: {0}/{1}".format(pass_count, total)
                
                MessageBox.Show(msg, "CI/CD Test Results",
                              MessageBoxButtons.OK,
                              MessageBoxIcon.Information if fail_count == 0 else MessageBoxIcon.Warning)
                if fail_count:
                    self.log_command("Test suite FAIL ({0}/{1} passed)".format(pass_count, total))
                else:
                    self.log_command("Test suite PASS ({0}/{1})".format(pass_count, total))
            else:
                err = result.get("error", "unknown error")
                MessageBox.Show("Test execution failed:\n" + err, "CI/CD Error",
                              MessageBoxButtons.OK, MessageBoxIcon.Error)
                self.log_command("FAIL tests: " + err)
        except Exception as e:
            MessageBox.Show("Exception running tests:\n" + str(e), "CI/CD Error",
                          MessageBoxButtons.OK, MessageBoxIcon.Error)
            self.log_command("CI/CD exception: " + str(e))
        Application.DoEvents()

    def _on_settings_click(self, sender, args):
        """Open settings window."""
        settings = SettingsForm()
        settings.ShowDialog(self)

    def show_window(self):
        """Show the form non-modally."""
        self.Show()
        Application.DoEvents()

    def close_window(self):
        """Close the form cleanly."""
        try:
            self.Close()
        except Exception:
            pass


def show_daemon_ui():
    """Create and show the daemon UI form. Returns the form object."""
    form = DaemonForm()
    form.show_window()
    return form


def pump_events(form):
    """Call from the main loop to keep UI responsive."""
    if form is not None:
        try:
            Application.DoEvents()
        except Exception:
            pass

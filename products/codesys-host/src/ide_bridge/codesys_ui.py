# -*- coding: utf-8 -*-
"""
codesys_ui.py - Minimal UI helpers for active XML-first commands.
"""
from __future__ import print_function
import codecs
import json
import os
import textwrap

# Pure decision logic for the settings dialogs; no CLR, safe to import here.
import settings_layers_model

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult,
        Form, Label, Button, CheckBox, Panel, ToolTip, FormBorderStyle,
        FormStartPosition, FlatStyle, ComboBox, TextBox, ComboBoxStyle,
        Control, Keys, ScrollBars
    )
    from System.Drawing import Size, Point, Font, FontStyle, Color, ContentAlignment
except Exception:
    MessageBox = None
    MessageBoxButtons = None
    MessageBoxIcon = None
    DialogResult = None
    Form = None
    Label = None
    Button = None
    CheckBox = None
    Panel = None
    ToolTip = None
    ComboBox = None
    TextBox = None
    ComboBoxStyle = None
    Control = None
    Keys = None
    ScrollBars = None
    FormBorderStyle = None
    FormStartPosition = None
    FlatStyle = None
    Size = None
    Point = None
    Font = None
    FontStyle = None
    Color = None
    ContentAlignment = None


def ask_yes_no(title, message):
    if MessageBox is not None:
        result = MessageBox.Show(message, title, MessageBoxButtons.YesNo, MessageBoxIcon.Question)
        return result == DialogResult.Yes
    return False


def ask_yes_no_cancel(title, message):
    if MessageBox is not None:
        result = MessageBox.Show(message, title, MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question)
        if result == DialogResult.Yes:
            return "yes"
        if result == DialogResult.No:
            return "no"
    return "cancel"


SYNC_FOLDER_PROMPT = (
    "Sync folder for this project. Relative paths resolve from the saved\n"
    "project file, so a teammate who clones the repository needs no change:\n"
    "    myproject-cts    a folder beside the .project file (suggested)\n"
    "    .                the project directory itself\n"
    "    C:\\MySync        an absolute path, this machine only\n"
    "The folder is created on first use if it does not exist yet."
)


class SyncFolderForm(Form if Form is not None else object):
    """One dialog for the sync folder: a suggested path, editable, plus Browse.

    Replaces the older two-step "pick a method, then browse or type" flow. The
    suggestion has to live in the text box rather than in the folder browser:
    FolderBrowserDialog silently ignores a preselected path that does not exist
    yet, so a suggested-but-not-yet-created folder never reaches the user
    there. Browsing stays one click away for the cases that need it.
    """

    def __init__(self, title, suggestion, browse=None):
        self.Text = title
        self.Size = Size(560, 320)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.path = None
        self._browse = browse

        lbl_msg = Label()
        lbl_msg.Text = "Sync Folder Setup"
        lbl_msg.Font = Font("Segoe UI", 14, FontStyle.Bold)
        lbl_msg.Location = Point(20, 18)
        lbl_msg.AutoSize = True
        lbl_msg.ForeColor = Color.FromArgb(50, 50, 50)
        self.Controls.Add(lbl_msg)

        lbl_sub = Label()
        lbl_sub.Text = SYNC_FOLDER_PROMPT
        lbl_sub.Font = Font("Segoe UI", 9)
        lbl_sub.Location = Point(22, 52)
        lbl_sub.Size = Size(510, 120)
        lbl_sub.ForeColor = Color.Gray
        self.Controls.Add(lbl_sub)

        lbl_path = Label()
        lbl_path.Text = "Folder:"
        lbl_path.Font = Font("Segoe UI", 9)
        lbl_path.Location = Point(22, 190)
        lbl_path.AutoSize = True
        self.Controls.Add(lbl_path)

        self.txt_path = TextBox()
        self.txt_path.Font = Font("Segoe UI", 10)
        self.txt_path.Location = Point(80, 187)
        self.txt_path.Size = Size(350, 24)
        self.txt_path.Text = suggestion or ""
        self.Controls.Add(self.txt_path)

        btn_browse = Button()
        btn_browse.Text = "Browse..."
        btn_browse.Font = Font("Segoe UI", 9)
        btn_browse.Location = Point(440, 186)
        btn_browse.Size = Size(90, 26)
        btn_browse.BackColor = Color.White
        btn_browse.FlatStyle = FlatStyle.Flat
        btn_browse.FlatAppearance.BorderColor = Color.LightGray
        btn_browse.Enabled = browse is not None
        btn_browse.Click += self._on_browse
        self.Controls.Add(btn_browse)

        btn_ok = Button()
        btn_ok.Text = "OK"
        btn_ok.Font = Font("Segoe UI", 9)
        btn_ok.Location = Point(350, 240)
        btn_ok.Size = Size(85, 28)
        btn_ok.Click += self._on_ok
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Font = Font("Segoe UI", 9)
        btn_cancel.Location = Point(445, 240)
        btn_cancel.Size = Size(85, 28)
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

        # The suggestion is the common answer: Enter accepts it, and a
        # pre-selected value is replaced by typing rather than edited. Set the
        # range directly - SelectAll() needs focus the form does not have yet.
        self.ActiveControl = self.txt_path
        self.txt_path.SelectionStart = 0
        self.txt_path.SelectionLength = len(self.txt_path.Text)

    def _on_browse(self, sender, event):
        if self._browse is None:
            return
        try:
            picked = self._browse()
        except Exception as error:
            print("Error showing folder browser: " + str(error))
            return
        if picked:
            self.txt_path.Text = picked

    def _on_ok(self, sender, event):
        text = (self.txt_path.Text or "").strip()
        if not text:
            return
        self.path = text
        self.DialogResult = DialogResult.OK
        self.Close()


def show_sync_folder_dialog(title, suggestion, browse=None, query=None):
    """Ask for the sync folder. Returns the entered path, or None to cancel.

    ``browse`` opens a folder browser and returns a path or None; ``query``
    is the plain-text fallback for environments without Windows Forms.
    """
    if Form is not None:
        try:
            form = SyncFolderForm(title, suggestion, browse)
            form.ShowDialog()
            return form.path
        except Exception as e:
            print("Error showing sync folder dialog: " + str(e))
    if query is not None:
        try:
            return query(SYNC_FOLDER_PROMPT, suggestion) or None
        except Exception as e:
            print("Error querying for the sync folder: " + str(e))
    return None


class OverwriteConfirmForm(Form if Form is not None else object):
    """Pre-export prompt for locally-modified and unmanaged view files.

    Both actions are independent, opt-in checkboxes with safe defaults:
      - overwrite locally-modified files (default off -> keep, pending import);
      - remove unmanaged derived files (default off -> keep).
    "Continue" proceeds with whatever is checked; "Cancel" aborts the export.
    """

    def __init__(self, dirty_paths, orphan_paths):
        self.Text = "Export - Local Changes Detected"
        self.Size = Size(560, 470)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.confirmed = False
        self.overwrite_dirty = False
        self.remove_orphans = False
        self._has_dirty = bool(dirty_paths)
        self._has_orphans = bool(orphan_paths)

        lbl_msg = Label()
        lbl_msg.Text = "Review local changes before export"
        lbl_msg.Font = Font("Segoe UI", 12, FontStyle.Bold)
        lbl_msg.Location = Point(20, 18)
        lbl_msg.AutoSize = True
        lbl_msg.ForeColor = Color.FromArgb(50, 50, 50)
        self.Controls.Add(lbl_msg)

        lbl_sub = Label()
        lbl_sub.Text = (
            "By default nothing here is touched: modified files are kept for the\n"
            "next import, and unmanaged files are left in place."
        )
        lbl_sub.Font = Font("Segoe UI", 9)
        lbl_sub.Location = Point(22, 46)
        lbl_sub.AutoSize = True
        lbl_sub.ForeColor = Color.Gray
        self.Controls.Add(lbl_sub)

        lines = []
        if dirty_paths:
            lines.append("Modified since last export (not yet imported):")
            for path in dirty_paths:
                lines.append("  " + path)
        if orphan_paths:
            if lines:
                lines.append("")
            lines.append("Unmanaged derived files (no longer produced):")
            for path in orphan_paths:
                lines.append("  " + path)

        txt_list = TextBox()
        txt_list.Multiline = True
        txt_list.ReadOnly = True
        txt_list.WordWrap = False
        if ScrollBars is not None:
            txt_list.ScrollBars = ScrollBars.Both
        txt_list.Font = Font("Consolas", 9)
        txt_list.Location = Point(22, 88)
        txt_list.Size = Size(500, 200)
        txt_list.Text = "\r\n".join(lines)
        self.Controls.Add(txt_list)

        y = 298
        self.chk_overwrite = CheckBox()
        self.chk_overwrite.Text = "Overwrite my local changes (discard un-imported edits)"
        self.chk_overwrite.Location = Point(22, y)
        self.chk_overwrite.Size = Size(500, 22)
        self.chk_overwrite.Checked = False
        self.chk_overwrite.Enabled = self._has_dirty
        self.Controls.Add(self.chk_overwrite)
        y += 26

        self.chk_remove_orphans = CheckBox()
        self.chk_remove_orphans.Text = "Remove the unmanaged derived files listed above"
        self.chk_remove_orphans.Location = Point(22, y)
        self.chk_remove_orphans.Size = Size(500, 22)
        self.chk_remove_orphans.Checked = False
        self.chk_remove_orphans.Enabled = self._has_orphans
        self.Controls.Add(self.chk_remove_orphans)

        btn_cancel = Button()
        btn_cancel.Text = "Cancel export"
        btn_cancel.Font = Font("Segoe UI", 9)
        btn_cancel.Location = Point(282, 388)
        btn_cancel.Size = Size(115, 30)
        btn_cancel.BackColor = Color.White
        btn_cancel.FlatStyle = FlatStyle.Flat
        btn_cancel.FlatAppearance.BorderColor = Color.LightGray
        btn_cancel.Click += self._on_cancel
        self.Controls.Add(btn_cancel)

        btn_continue = Button()
        btn_continue.Text = "Continue"
        btn_continue.Font = Font("Segoe UI", 9)
        btn_continue.Location = Point(405, 388)
        btn_continue.Size = Size(140, 30)
        btn_continue.BackColor = Color.White
        btn_continue.FlatStyle = FlatStyle.Flat
        btn_continue.FlatAppearance.BorderColor = Color.LightGray
        btn_continue.Click += self._on_continue
        self.Controls.Add(btn_continue)

        self.AcceptButton = btn_continue
        self.CancelButton = btn_cancel

    def _on_continue(self, sender, event):
        self.confirmed = True
        self.overwrite_dirty = bool(self.chk_overwrite.Checked)
        self.remove_orphans = bool(self.chk_remove_orphans.Checked)
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_cancel(self, sender, event):
        self.confirmed = False
        self.DialogResult = DialogResult.Cancel
        self.Close()


def show_overwrite_confirm_dialog(dirty_paths, orphan_paths):
    """Return a dict {overwrite_dirty, remove_orphans} to proceed, or None to
    cancel the export."""
    dirty_paths = list(dirty_paths or [])
    orphan_paths = list(orphan_paths or [])
    if Form is not None:
        try:
            form = OverwriteConfirmForm(dirty_paths, orphan_paths)
            result = form.ShowDialog()
            if result != DialogResult.OK or not form.confirmed:
                return None
            return {
                "overwrite_dirty": bool(form.overwrite_dirty),
                "remove_orphans": bool(form.remove_orphans),
            }
        except Exception as e:
            print("Error showing overwrite confirm dialog: " + str(e))
    # Fallback without WinForms: proceed safely (keep everything).
    return {"overwrite_dirty": False, "remove_orphans": False}


def show_toast(title, message, timeout=3000):
    print("%s: %s" % (title, message))


class ProjectOptionsForm(Form if Form is not None else object):
    LAYOUTS = [
        ("project-view", "Project folder: project-view/"),
        ("root-view", "Root of project"),
    ]

    def __init__(self, current_settings):
        self.Text = "cds-text-sync: Project Options"
        self.Size = Size(660, 800)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.result_settings = None
        self.result_pinned = None
        self.projection_controls = []
        self.xml_in_view_controls = []
        # name -> (inherit checkbox, value control) for every behavior key.
        self._behavior_controls = {}
        self._base_settings = dict(current_settings)
        self._inherited_values = settings_layers_model.inherited_behavior_values()
        self._behavior_hints = settings_layers_model.behavior_hints()
        sources = current_settings.get("_sources")
        if sources is None:
            # No layer read was handed over: treat every behavior key as
            # pinned, so the controls stay editable exactly as before.
            sources = dict(
                (name, "project")
                for name in settings_layers_model.behavior_names()
            )
        self._behavior_rows = dict(
            (row["name"], row)
            for row in settings_layers_model.behavior_rows(current_settings, sources)
        )
        self.view_root_locked = bool(current_settings.get("_view_root_locked"))
        self.sync_mode_locked = bool(current_settings.get("_sync_mode_locked"))
        self.initial_layout = current_settings.get("layout") or "project-view"
        self.initial_view_root = current_settings.get("view_root") or None
        self.initial_sync_mode = (
            current_settings.get("_sync_mode_lock_value")
            if self.sync_mode_locked
            else current_settings.get("sync_mode")
        ) or "xml_first"

        self._build_header()

        lbl_layout = Label()
        lbl_layout.Text = "View storage"
        lbl_layout.Location = Point(24, 88)
        lbl_layout.Size = Size(120, 20)
        self.Controls.Add(lbl_layout)

        self.cmb_layout = ComboBox()
        self.cmb_layout.Location = Point(150, 85)
        self.cmb_layout.Size = Size(310, 24)
        self.cmb_layout.DropDownStyle = ComboBoxStyle.DropDownList
        for layout_id, layout_label in self.LAYOUTS:
            self.cmb_layout.Items.Add(layout_label)
        current_layout = current_settings.get("layout") or "project-view"
        selected_index = 0
        for index, (layout_id, layout_label) in enumerate(self.LAYOUTS):
            if layout_id == current_layout:
                selected_index = index
                break
        self.cmb_layout.SelectedIndex = selected_index
        self.cmb_layout.SelectedIndexChanged += self._on_layout_changed
        self.cmb_layout.Enabled = not self.view_root_locked
        self.Controls.Add(self.cmb_layout)

        lbl_layout_help = Label()
        if self.view_root_locked:
            lbl_layout_help.Text = "Folder choice is locked after first export."
        else:
            lbl_layout_help.Text = "Choose where generated views live by default."
        lbl_layout_help.Location = Point(150, 111)
        lbl_layout_help.Size = Size(340, 18)
        lbl_layout_help.ForeColor = Color.FromArgb(110, 110, 110)
        lbl_layout_help.Font = Font("Segoe UI", 8)
        self.Controls.Add(lbl_layout_help)

        self.chk_custom_view_root = CheckBox()
        self.chk_custom_view_root.Text = "Use custom view root"
        self.chk_custom_view_root.Location = Point(150, 132)
        self.chk_custom_view_root.Size = Size(200, 22)
        self.chk_custom_view_root.Checked = bool(current_settings.get("view_root"))
        self.chk_custom_view_root.CheckedChanged += self._on_custom_view_root_changed
        self.chk_custom_view_root.Enabled = not self.view_root_locked
        self.Controls.Add(self.chk_custom_view_root)

        lbl_view_root = Label()
        lbl_view_root.Text = "Custom view root"
        lbl_view_root.Location = Point(24, 160)
        lbl_view_root.Size = Size(120, 20)
        self.Controls.Add(lbl_view_root)

        self.txt_view_root = TextBox()
        self.txt_view_root.Location = Point(150, 157)
        self.txt_view_root.Size = Size(310, 22)
        self.txt_view_root.Text = current_settings.get("view_root") or ""
        self.txt_view_root.Enabled = bool(current_settings.get("view_root")) and not self.view_root_locked
        self.txt_view_root.TextChanged += self._on_view_root_changed
        self.Controls.Add(self.txt_view_root)

        self.lbl_view_root_mode = Label()
        self.lbl_view_root_mode.Text = ""
        self.lbl_view_root_mode.Location = Point(150, 181)
        self.lbl_view_root_mode.Size = Size(340, 34)
        self.lbl_view_root_mode.ForeColor = Color.FromArgb(110, 110, 110)
        self.lbl_view_root_mode.Font = Font("Segoe UI", 8)
        self.Controls.Add(self.lbl_view_root_mode)

        hint = Label()
        if self.view_root_locked:
            hint.Text = "To choose another folder, start over with a clean sync directory."
        else:
            hint.Text = "Leave custom view root off to use the preset. Relative paths stay portable."
        hint.Location = Point(150, 216)
        hint.Size = Size(340, 34)
        hint.ForeColor = Color.FromArgb(110, 110, 110)
        hint.Font = Font("Segoe UI", 8)
        self.Controls.Add(hint)

        self._build_profile_controls(current_settings)

        self._build_sync_mode_controls()

        self._build_view_lists(current_settings)

        self._build_backup_controls(current_settings)

        self._build_dialog_buttons()

    def _build_dialog_buttons(self):
        self.btn_reset_formats = Button()
        self.btn_reset_formats.Text = "Reset to defaults"
        self.btn_reset_formats.Location = Point(24, 724)
        self.btn_reset_formats.Size = Size(140, 28)
        self.btn_reset_formats.Click += self._on_reset_formats
        self.Controls.Add(self.btn_reset_formats)

        self.btn_cts_defaults = Button()
        self.btn_cts_defaults.Text = "CTS Defaults..."
        self.btn_cts_defaults.Location = Point(172, 724)
        self.btn_cts_defaults.Size = Size(120, 28)
        self.btn_cts_defaults.Click += self._on_open_cts_defaults
        self.Controls.Add(self.btn_cts_defaults)

        btn_ok = Button()
        btn_ok.Text = "Save"
        btn_ok.Location = Point(424, 724)
        btn_ok.Size = Size(85, 28)
        btn_ok.Click += self._on_save
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Location = Point(516, 724)
        btn_cancel.Size = Size(85, 28)
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel
        self._refresh_view_root_state()
        self._refresh_view_root_summary()
        self._refresh_sync_mode_panels()

    def _apply_format_values(self, values):
        """Fill the format controls from a values dict, without saving."""
        layout = values.get("layout")
        if layout and not self.view_root_locked:
            for index, (layout_id, _label) in enumerate(self.LAYOUTS):
                if layout_id == layout:
                    self.cmb_layout.SelectedIndex = index
                    break
        profile = values.get("profile")
        if profile:
            items = [str(self.cmb_profile.Items[index]) for index in range(self.cmb_profile.Items.Count)]
            if profile not in items:
                self.cmb_profile.Items.Add(profile)
                items.append(profile)
            self.cmb_profile.SelectedIndex = items.index(profile)
        if not self.sync_mode_locked and values.get("sync_mode"):
            self.chk_text_first.Checked = values.get("sync_mode") == "text_first"
        if isinstance(values.get("projections"), dict):
            enabled_map = {"projections": values.get("projections")}
            for checkbox in self.projection_controls:
                if checkbox.Tag:
                    checkbox.Checked = self._projection_enabled(enabled_map, checkbox.Tag)
        kinds = values.get("xml_in_view_kinds")
        if isinstance(kinds, (list, tuple)):
            wanted = [str(kind).strip().lower() for kind in kinds]
            for checkbox in self.xml_in_view_controls:
                checkbox.Checked = str(checkbox.Tag).strip().lower() in wanted
        self._refresh_sync_mode_panels()

    def _on_reset_formats(self, sender, event):
        """Fill the format controls from the user defaults; nothing is saved."""
        try:
            values = settings_layers_model.format_reset_values()
        except Exception as exc:
            print("Error reading user defaults: " + str(exc))
            return
        self._apply_format_values(values)

    def _on_open_cts_defaults(self, sender, event):
        """Open the per-user defaults window, then refresh inherited values."""
        if not show_user_defaults_dialog():
            return
        try:
            self._inherited_values = settings_layers_model.inherited_behavior_values()
            self._behavior_hints = settings_layers_model.behavior_hints()
        except Exception as exc:
            print("Error reading user defaults: " + str(exc))
            return
        for name, pair in self._behavior_controls.items():
            checkbox, control = pair
            hint = self._behavior_hints.get(name, "built-in")
            checkbox.Text = "Inherit (" + hint + ")"
            if checkbox.Checked:
                self._set_behavior_value(name, self._inherited_values.get(name))
                control.Enabled = False

    def _build_header(self):
        title = Label()
        title.Text = "Project Sync Options"
        title.Font = Font("Segoe UI", 14, FontStyle.Bold)
        title.Location = Point(20, 18)
        title.Size = Size(460, 28)
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = "These settings are saved to cds-text-sync.json in the sync root."
        subtitle.Font = Font("Segoe UI", 9)
        subtitle.ForeColor = Color.FromArgb(90, 90, 90)
        subtitle.Location = Point(22, 50)
        subtitle.Size = Size(460, 22)
        self.Controls.Add(subtitle)

    def _build_profile_controls(self, current_settings):
        lbl_profile = Label()
        lbl_profile.Text = "Profile"
        lbl_profile.Location = Point(24, 252)
        lbl_profile.Size = Size(120, 20)
        self.Controls.Add(lbl_profile)

        self.cmb_profile = ComboBox()
        self.cmb_profile.Location = Point(150, 249)
        self.cmb_profile.Size = Size(310, 24)
        self.cmb_profile.DropDownStyle = ComboBoxStyle.DropDownList
        profiles = current_settings.get("_available_profiles") or []
        profile_ids = []
        for profile in profiles:
            profile_id = profile.get("id") or profile.get("name")
            if profile_id and profile_id not in profile_ids:
                profile_ids.append(profile_id)
        current_profile = current_settings.get("profile") or "default"
        if current_profile not in profile_ids:
            profile_ids.insert(0, current_profile)
        for profile_id in profile_ids:
            self.cmb_profile.Items.Add(profile_id)
        self.cmb_profile.SelectedIndex = (
            profile_ids.index(current_profile) if current_profile in profile_ids else 0
        )
        self.Controls.Add(self.cmb_profile)

    def _build_sync_mode_controls(self):
        lbl_sync_mode = Label()
        lbl_sync_mode.Text = "Sync mode"
        lbl_sync_mode.Location = Point(24, 290)
        lbl_sync_mode.Size = Size(120, 20)
        self.Controls.Add(lbl_sync_mode)

        self.chk_text_first = CheckBox()
        self.chk_text_first.Text = "Text-first mode (.st files are the source of truth)"
        self.chk_text_first.Location = Point(150, 286)
        self.chk_text_first.Size = Size(360, 22)
        self.chk_text_first.Checked = self.initial_sync_mode == "text_first"
        self.chk_text_first.Enabled = not self.sync_mode_locked
        self.chk_text_first.CheckedChanged += self._on_text_first_changed
        self.Controls.Add(self.chk_text_first)

        lbl_sync_mode_help = Label()
        if self.sync_mode_locked:
            lbl_sync_mode_help.Text = (
                "Mode is fixed at initialization. To switch, initialize a new "
                "empty sync folder."
            )
        else:
            lbl_sync_mode_help.Text = (
                "Choose before the first export. Text-first hides native XML in "
                ".dump/xml and ST files drive import."
            )
        lbl_sync_mode_help.Location = Point(150, 310)
        lbl_sync_mode_help.Size = Size(370, 30)
        lbl_sync_mode_help.ForeColor = Color.FromArgb(110, 110, 110)
        lbl_sync_mode_help.Font = Font("Segoe UI", 8)
        self.Controls.Add(lbl_sync_mode_help)

    def _build_view_lists(self, current_settings):
        self.lbl_list = Label()
        self.lbl_list.Location = Point(24, 352)
        self.lbl_list.Size = Size(120, 20)
        self.Controls.Add(self.lbl_list)

        self.projections_panel = Panel()
        self.projections_panel.Location = Point(150, 348)
        self.projections_panel.Size = Size(360, 118)
        self.projections_panel.AutoScroll = False
        self.projections_panel.BackColor = Color.White
        self.Controls.Add(self.projections_panel)
        self._add_projection_options(current_settings)

        self.xml_in_view_panel = Panel()
        self.xml_in_view_panel.Location = Point(150, 348)
        self.xml_in_view_panel.Size = Size(360, 118)
        self.xml_in_view_panel.AutoScroll = True
        self.xml_in_view_panel.BackColor = Color.White
        self.Controls.Add(self.xml_in_view_panel)
        self._add_xml_in_view_options(current_settings)

        self.list_hint = Label()
        self.list_hint.Location = Point(150, 470)
        self.list_hint.Size = Size(370, 20)
        self.list_hint.ForeColor = Color.FromArgb(110, 110, 110)
        self.list_hint.Font = Font("Segoe UI", 8)
        self.Controls.Add(self.list_hint)

    def _add_inherit_checkbox(self, name, control, x, y):
        """Pair a behavior control with its "Inherit" box and wire the two.

        Checked means "not pinned": the control shows the inherited value,
        disabled. Unchecked means the project file owns the value, so the
        control is editable and saving re-pins it.
        """
        row = self._behavior_rows.get(name) or {"pinned": True}
        checkbox = CheckBox()
        checkbox.Text = "Inherit (" + self._behavior_hints.get(name, "built-in") + ")"
        checkbox.Location = Point(x, y)
        checkbox.Size = Size(170, 22)
        checkbox.Checked = not row.get("pinned", True)
        checkbox.CheckedChanged += self._make_inherit_handler(name)
        self.Controls.Add(checkbox)
        self._behavior_controls[name] = (checkbox, control)
        control.Enabled = not checkbox.Checked
        return checkbox

    def _make_inherit_handler(self, name):
        def _handler(sender, event):
            self._on_behavior_inherit_changed(name)
        return _handler

    def _on_behavior_inherit_changed(self, name):
        pair = self._behavior_controls.get(name)
        if not pair:
            return
        checkbox, control = pair
        if checkbox.Checked:
            self._set_behavior_value(name, self._inherited_values.get(name))
            control.Enabled = False
        else:
            control.Enabled = True

    def _behavior_value(self, name):
        if name == "pre_import_backup_enabled":
            return bool(self.chk_pre_import_backup.Checked)
        if name == "backup_retention_count":
            return self._backup_retention_count()
        if name == "verbose_logging":
            return bool(self.chk_verbose_logging.Checked)
        if name == "advanced_debug":
            return bool(self.chk_advanced_debug.Checked)
        if name == "show_completion_popup":
            return bool(self.chk_completion_popup.Checked)
        return None

    def _set_behavior_value(self, name, value):
        if name == "pre_import_backup_enabled":
            self.chk_pre_import_backup.Checked = bool(value)
        elif name == "backup_retention_count":
            self.txt_backup_retention.Text = str(value if value is not None else 10)
        elif name == "verbose_logging":
            self.chk_verbose_logging.Checked = bool(value)
        elif name == "advanced_debug":
            self.chk_advanced_debug.Checked = bool(value)
        elif name == "show_completion_popup":
            self.chk_completion_popup.Checked = bool(value)

    def _build_backup_controls(self, current_settings):
        lbl_backup = Label()
        lbl_backup.Text = "Safety backup"
        lbl_backup.Location = Point(24, 496)
        lbl_backup.Size = Size(120, 20)
        self.Controls.Add(lbl_backup)

        self.chk_pre_import_backup = CheckBox()
        self.chk_pre_import_backup.Text = "Backup before import"
        self.chk_pre_import_backup.Location = Point(150, 496)
        self.chk_pre_import_backup.Size = Size(300, 22)
        self.chk_pre_import_backup.Checked = bool(current_settings.get("pre_import_backup_enabled", True))
        self.Controls.Add(self.chk_pre_import_backup)
        self._add_inherit_checkbox("pre_import_backup_enabled", self.chk_pre_import_backup, 458, 496)

        lbl_retention = Label()
        lbl_retention.Text = "Max backups"
        lbl_retention.Location = Point(150, 524)
        lbl_retention.Size = Size(110, 20)
        self.Controls.Add(lbl_retention)

        self.txt_backup_retention = TextBox()
        self.txt_backup_retention.Location = Point(264, 521)
        self.txt_backup_retention.Size = Size(50, 22)
        self.txt_backup_retention.Text = str(current_settings.get("backup_retention_count", 10))
        self.Controls.Add(self.txt_backup_retention)
        self._add_inherit_checkbox("backup_retention_count", self.txt_backup_retention, 458, 524)

        backup_hint = Label()
        backup_hint.Text = "Timestamped project binaries are written to .backup/ before IDE changes."
        backup_hint.Location = Point(150, 550)
        backup_hint.Size = Size(470, 20)
        backup_hint.ForeColor = Color.FromArgb(110, 110, 110)
        backup_hint.Font = Font("Segoe UI", 8)
        self.Controls.Add(backup_hint)

        self.chk_verbose_logging = CheckBox()
        self.chk_verbose_logging.Text = "Save detailed engine logs in .dump"
        self.chk_verbose_logging.Location = Point(150, 574)
        self.chk_verbose_logging.Size = Size(300, 22)
        self.chk_verbose_logging.Checked = bool(current_settings.get("verbose_logging", False))
        self.Controls.Add(self.chk_verbose_logging)
        self._add_inherit_checkbox("verbose_logging", self.chk_verbose_logging, 458, 574)

        self.chk_advanced_debug = CheckBox()
        self.chk_advanced_debug.Text = "Advanced debug: also log IDE script messages"
        self.chk_advanced_debug.Location = Point(150, 602)
        self.chk_advanced_debug.Size = Size(300, 22)
        self.chk_advanced_debug.Checked = bool(current_settings.get("advanced_debug", False))
        self.Controls.Add(self.chk_advanced_debug)
        self._add_inherit_checkbox("advanced_debug", self.chk_advanced_debug, 458, 602)

        self.chk_completion_popup = CheckBox()
        self.chk_completion_popup.Text = "Show completion summary after import/export"
        self.chk_completion_popup.Location = Point(150, 630)
        self.chk_completion_popup.Size = Size(300, 22)
        self.chk_completion_popup.Checked = bool(current_settings.get("show_completion_popup", True))
        self.Controls.Add(self.chk_completion_popup)
        self._add_inherit_checkbox("show_completion_popup", self.chk_completion_popup, 458, 630)

        self.chk_gitignore = CheckBox()
        self.chk_gitignore.Text = "Add recommended .gitignore entries"
        self.chk_gitignore.Location = Point(150, 658)
        self.chk_gitignore.Size = Size(310, 22)
        self.chk_gitignore.Checked = bool(current_settings.get("_ensure_gitignore", False))
        self.Controls.Add(self.chk_gitignore)

        behavior_hint = Label()
        behavior_hint.Text = (
            "Inherit keeps the value from your user defaults (or the built-in "
            "default) and stores nothing here. Uncheck to pin a value in "
            "cds-text-sync.json for this project."
        )
        behavior_hint.Location = Point(150, 684)
        behavior_hint.Size = Size(470, 34)
        behavior_hint.ForeColor = Color.FromArgb(110, 110, 110)
        behavior_hint.Font = Font("Segoe UI", 8)
        self.Controls.Add(behavior_hint)

    def _projection_enabled(self, current_settings, projection):
        current = current_settings.get("projections") or {}
        projection_id = projection.get("id")
        kind = projection.get("kind")
        if projection_id in current:
            value = current.get(projection_id)
            if isinstance(value, dict):
                return bool(value.get("enabled", True))
            return bool(value)
        if kind in current:
            return True
        return bool(projection.get("default_enabled", False))

    def _selected_layout_value(self):
        if self.cmb_layout.SelectedIndex < 0:
            return "project-view"
        if self.cmb_layout.SelectedIndex >= len(self.LAYOUTS):
            return "project-view"
        return self.LAYOUTS[self.cmb_layout.SelectedIndex][0]

    def _refresh_view_root_state(self):
        if hasattr(self, "txt_view_root") and hasattr(self, "chk_custom_view_root"):
            self.txt_view_root.Enabled = bool(self.chk_custom_view_root.Checked) and not self.view_root_locked

    def _refresh_view_root_summary(self):
        if not hasattr(self, "lbl_view_root_mode"):
            return
        if self.view_root_locked:
            locked_value = self.initial_view_root
            if locked_value:
                self.lbl_view_root_mode.Text = "Locked path: custom view root = {0}".format(locked_value)
            elif self.initial_layout == "root-view":
                self.lbl_view_root_mode.Text = "Locked path: sync root"
            else:
                self.lbl_view_root_mode.Text = "Locked path: project-view/"
            return
        layout_value = self._selected_layout_value()
        if layout_value == "project-view":
            default_text = "Default: project-view/"
        else:
            default_text = "Default: sync root"

        custom_path = self.txt_view_root.Text.strip() if hasattr(self, "txt_view_root") else ""
        if self.chk_custom_view_root.Checked and custom_path:
            self.lbl_view_root_mode.Text = "Active path: custom view root = {0}".format(custom_path)
        elif self.chk_custom_view_root.Checked:
            self.lbl_view_root_mode.Text = "Custom view root is enabled, but the path is empty."
        else:
            self.lbl_view_root_mode.Text = default_text

    def _on_layout_changed(self, sender, event):
        self._refresh_view_root_summary()

    def _on_custom_view_root_changed(self, sender, event):
        self._refresh_view_root_state()
        self._refresh_view_root_summary()

    def _on_view_root_changed(self, sender, event):
        self._refresh_view_root_summary()

    def _add_projection_options(self, current_settings):
        options = current_settings.get("_available_projections") or []
        if not options:
            empty = Label()
            empty.Text = "No optional projections in selected profile."
            empty.Location = Point(8, 8)
            empty.Size = Size(320, 20)
            empty.ForeColor = Color.FromArgb(110, 110, 110)
            self.projections_panel.Controls.Add(empty)
            return

        y = 6
        for projection in options:
            checkbox = CheckBox()
            checkbox.Text = projection.get("label") or projection.get("id") or projection.get("kind") or "projection"
            checkbox.Location = Point(8, y)
            checkbox.Size = Size(320, 22)
            checkbox.Checked = self._projection_enabled(current_settings, projection)
            checkbox.Tag = projection
            self.projections_panel.Controls.Add(checkbox)
            self.projection_controls.append(checkbox)
            y += 24

    def _selected_projections(self):
        selected = {}
        for checkbox in self.projection_controls:
            if not checkbox.Checked or not checkbox.Tag:
                continue
            projection = checkbox.Tag
            projection_id = projection.get("id") or projection.get("kind")
            if not projection_id:
                continue
            selected[projection_id] = {
                "enabled": True,
                "kind": projection.get("kind"),
                "format": projection.get("format"),
                "import_safe": bool(projection.get("import_safe", False)),
            }
        return selected

    def _add_xml_in_view_options(self, current_settings):
        kinds = current_settings.get("_available_xml_in_view_kinds") or []
        selected_kinds = [
            str(kind).strip().lower()
            for kind in (current_settings.get("xml_in_view_kinds") or [])
        ]
        if not kinds:
            empty = Label()
            empty.Text = "No XML-only kinds in selected profile."
            empty.Location = Point(8, 8)
            empty.Size = Size(320, 20)
            empty.ForeColor = Color.FromArgb(110, 110, 110)
            self.xml_in_view_panel.Controls.Add(empty)
            return

        y = 6
        for kind in kinds:
            checkbox = CheckBox()
            checkbox.Text = kind
            checkbox.Location = Point(8, y)
            checkbox.Size = Size(320, 22)
            checkbox.Checked = str(kind).strip().lower() in selected_kinds
            checkbox.Tag = kind
            self.xml_in_view_panel.Controls.Add(checkbox)
            self.xml_in_view_controls.append(checkbox)
            y += 24

    def _selected_xml_in_view_kinds(self):
        selected = []
        for checkbox in self.xml_in_view_controls:
            if checkbox.Checked and checkbox.Tag:
                selected.append(str(checkbox.Tag).strip().lower())
        return selected

    def _text_first_selected(self):
        if self.sync_mode_locked:
            return self.initial_sync_mode == "text_first"
        return bool(self.chk_text_first.Checked)

    def _refresh_sync_mode_panels(self):
        # The two derived-file lists are mutually exclusive by paradigm, so only
        # the one matching the selected mode is shown (the other's checkboxes are
        # kept but hidden, preserving their saved values). xml-first: choose which
        # .st/.csv views to derive. text-first: ST is forced on, so instead choose
        # which kinds keep their native .xml in the view vs. the .dump/xml mirror.
        text_first = self._text_first_selected()
        self.projections_panel.Visible = not text_first
        self.xml_in_view_panel.Visible = text_first
        if text_first:
            self.lbl_list.Text = "Keep XML in view"
            self.list_hint.Text = (
                "These kinds keep their native .xml in the view; every other "
                "kind's XML moves to the .dump/xml mirror."
            )
        else:
            self.lbl_list.Text = "Derived views"
            self.list_hint.Text = (
                "Enabled .st views own text on disk; XML is rehydrated internally."
            )

    def _on_text_first_changed(self, sender, event):
        self._refresh_sync_mode_panels()

    def _backup_retention_count(self):
        try:
            value = int(self.txt_backup_retention.Text.strip())
            if value >= 1:
                return value
        except Exception:
            pass
        return 10

    def _on_save(self, sender, event):
        view_root_value = None
        layout_value = self._selected_layout_value()
        if self.view_root_locked:
            layout_value = self.initial_layout
            view_root_value = self.initial_view_root
        elif self.chk_custom_view_root.Checked:
            view_root_value = self.txt_view_root.Text.strip() or None
        if self.sync_mode_locked:
            sync_mode_value = self.initial_sync_mode
        else:
            sync_mode_value = (
                "text_first" if self.chk_text_first.Checked else "xml_first"
            )
        format_values = {
            "layout": layout_value,
            "view_root": view_root_value,
            "profile": str(self.cmb_profile.SelectedItem) or "default",
            "projections": self._selected_projections(),
            "sync_mode": sync_mode_value,
            "xml_in_view_kinds": self._selected_xml_in_view_kinds(),
        }
        behavior_values = {}
        pinned = []
        for name, pair in self._behavior_controls.items():
            checkbox, _control = pair
            if checkbox.Checked:
                # Not pinned: hand back the inherited value so the writer
                # omits the key and the project keeps inheriting.
                behavior_values[name] = self._inherited_values.get(name)
            else:
                behavior_values[name] = self._behavior_value(name)
                pinned.append(name)
        self.result_settings, self.result_pinned = settings_layers_model.assemble_project_save(
            self._base_settings, format_values, behavior_values, pinned
        )
        self.result_settings["_ensure_gitignore"] = bool(self.chk_gitignore.Checked)
        self.result_settings["_pinned_behavior"] = self.result_pinned
        self.DialogResult = DialogResult.OK
        self.Close()


def show_project_options_dialog(current_settings):
    if Form is not None:
        try:
            form = ProjectOptionsForm(current_settings)
            result = form.ShowDialog()
            if result == DialogResult.OK:
                return form.result_settings
            return None
        except Exception as e:
            print("Error showing project options dialog: " + str(e))
    return None


class UserDefaultsForm(Form if Form is not None else object):
    """Edits the sparse per-user defaults file (``%APPDATA%\\cds-text-sync\\defaults.json``).

    Personal and per-machine: format keys seed a new project, behavior keys are
    inherited unless a project pins them. Saving keeps the file sparse (a value
    equal to the built-in default disappears). A file that cannot be read shows
    its error but does not block a save -- overwriting it is the fix.
    """

    LAYOUTS = ["project-view", "root-view", "legacy-dump-views"]
    SYNC_MODES = ["xml_first", "text_first"]

    LABELS = {
        "layout": "View storage",
        "profile": "Profile",
        "sync_mode": "Sync mode",
        "projections": "Projections (JSON)",
        "xml_in_view_kinds": "XML kinds in view",
        "verbose_logging": "Save detailed engine logs in .dump",
        "advanced_debug": "Advanced debug: also log IDE script messages",
        "show_completion_popup": "Show completion summary after import/export",
        "pre_import_backup_enabled": "Backup before import",
        "backup_retention_count": "Max backups",
    }

    def __init__(self, path, rows, status, error):
        self.Text = "cds-text-sync: CTS Defaults"
        self.Size = Size(620, 600)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.path = path
        self.saved = False
        self.rows = list(rows)
        self.combo_controls = {}
        self.check_controls = {}
        self.text_controls = {}
        self._row_kind = {}
        for row in self.rows:
            name = row["name"]
            if isinstance(row["value"], bool):
                self._row_kind[name] = "check"
            elif name in ("layout", "sync_mode"):
                self._row_kind[name] = "combo"
            else:
                self._row_kind[name] = "text"
        self._status = status
        self._error = error

        self._build_header()
        self._build_rows()

    def _build_header(self):
        title = Label()
        title.Text = "CTS Defaults"
        title.Font = Font("Segoe UI", 14, FontStyle.Bold)
        title.Location = Point(20, 18)
        title.Size = Size(460, 28)
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = "Your personal defaults on this machine. Nothing here is committed."
        subtitle.Font = Font("Segoe UI", 9)
        subtitle.ForeColor = Color.FromArgb(90, 90, 90)
        subtitle.Location = Point(22, 50)
        subtitle.Size = Size(570, 20)
        self.Controls.Add(subtitle)

        path_label = Label()
        path_label.Text = self.path
        path_label.Font = Font("Segoe UI", 8)
        path_label.ForeColor = Color.FromArgb(110, 110, 110)
        path_label.Location = Point(22, 72)
        path_label.Size = Size(570, 18)
        self.Controls.Add(path_label)

        if self._status == "invalid" and self._error:
            self.lbl_error = Label()
            self.lbl_error.Text = "Defaults file could not be read: " + self._error
            self.lbl_error.Font = Font("Segoe UI", 8)
            self.lbl_error.ForeColor = Color.FromArgb(160, 40, 40)
            self.lbl_error.Location = Point(22, 92)
            self.lbl_error.Size = Size(570, 30)
            self.Controls.Add(self.lbl_error)

    def _add_section_heading(self, text, y):
        heading = Label()
        heading.Text = text
        heading.Font = Font("Segoe UI", 9, FontStyle.Bold)
        heading.Location = Point(22, y)
        heading.Size = Size(320, 20)
        self.Controls.Add(heading)

    def _add_control(self, row, y):
        name = row["name"]
        kind = self._row_kind[name]
        if kind == "check":
            control = CheckBox()
            control.Text = self.LABELS.get(name, name)
            control.Location = Point(32, y)
            control.Size = Size(520, 22)
            control.Checked = bool(row["value"])
            self.Controls.Add(control)
            self.check_controls[name] = control
            return
        label = Label()
        label.Text = self.LABELS.get(name, name)
        label.Location = Point(32, y + 3)
        label.Size = Size(150, 20)
        self.Controls.Add(label)
        if kind == "combo":
            control = ComboBox()
            control.DropDownStyle = ComboBoxStyle.DropDownList
            choices = self.LAYOUTS if name == "layout" else self.SYNC_MODES
            value = row["value"]
            if value not in choices:
                choices = choices + [value]
            for choice in choices:
                control.Items.Add(choice)
            control.SelectedIndex = choices.index(value)
            control.Location = Point(190, y)
            control.Size = Size(160, 24)
            self.Controls.Add(control)
            self.combo_controls[name] = control
            return
        control = TextBox()
        control.Location = Point(190, y)
        if name in ("projections", "xml_in_view_kinds"):
            control.Size = Size(300, 22)
        else:
            control.Size = Size(120, 22)
        control.Text = self._row_text(name, row["value"])
        self.Controls.Add(control)
        self.text_controls[name] = control

    def _build_rows(self):
        self._add_section_heading("Format (seeds new projects)", 128)
        y = 152
        for row in self.rows:
            if row["class"] != "format":
                continue
            self._add_control(row, y)
            y += 30

        self._add_section_heading("Behavior (inherited by projects)", y + 12)
        y += 36
        for row in self.rows:
            if row["class"] != "behavior":
                continue
            self._add_control(row, y)
            y += 28

        note = Label()
        note.Text = (
            "A value equal to the built-in default is not stored, so a key added "
            "in a later version keeps its new default."
        )
        note.Location = Point(32, y + 12)
        note.Size = Size(560, 20)
        note.ForeColor = Color.FromArgb(110, 110, 110)
        note.Font = Font("Segoe UI", 8)
        self.Controls.Add(note)

        btn_reset = Button()
        btn_reset.Text = "Reset all to built-in"
        btn_reset.Location = Point(32, y + 40)
        btn_reset.Size = Size(150, 28)
        btn_reset.Click += self._on_reset_all
        self.Controls.Add(btn_reset)

        btn_save = Button()
        btn_save.Text = "Save"
        btn_save.Location = Point(424, y + 40)
        btn_save.Size = Size(85, 28)
        btn_save.Click += self._on_save
        self.Controls.Add(btn_save)
        self.AcceptButton = btn_save

        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Location = Point(516, y + 40)
        btn_cancel.Size = Size(85, 28)
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

    def _row_text(self, name, value):
        if name == "projections":
            if not value:
                return ""
            return json.dumps(value, sort_keys=True)
        if name == "xml_in_view_kinds":
            if not value:
                return ""
            return ", ".join(str(item) for item in value)
        if value is None:
            return ""
        return str(value)

    def _collect_raw(self):
        raw = {}
        for name, control in self.combo_controls.items():
            raw[name] = str(control.SelectedItem)
        for name, control in self.check_controls.items():
            raw[name] = bool(control.Checked)
        for name, control in self.text_controls.items():
            raw[name] = control.Text
        return raw

    def _apply_values(self, values):
        for name, control in self.combo_controls.items():
            value = values.get(name)
            items = [str(control.Items[index]) for index in range(control.Items.Count)]
            if value not in items:
                control.Items.Add(value)
                items.append(value)
            control.SelectedIndex = items.index(value)
        for name, control in self.check_controls.items():
            control.Checked = bool(values.get(name))
        for name, control in self.text_controls.items():
            control.Text = self._row_text(name, values.get(name))

    def _on_reset_all(self, sender, event):
        """Set every control to its built-in default; nothing is saved yet."""
        self._apply_values(settings_layers_model.reset_user_rows(self.path))

    def _on_save(self, sender, event):
        written, error = settings_layers_model.save_user_defaults(
            self._collect_raw(), self.path
        )
        if error:
            if MessageBox is not None:
                MessageBox.Show(
                    error, "Cannot Save Defaults",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning,
                )
            else:
                print("Cannot save defaults: " + error)
            return
        self.saved = True
        self.DialogResult = DialogResult.OK
        self.Close()


def show_user_defaults_dialog(path=None):
    """Open the CTS Defaults window. Returns True when the file was saved."""
    if Form is None:
        return False
    try:
        path, rows, status, error = settings_layers_model.user_defaults_state(path)
        form = UserDefaultsForm(path, rows, status, error)
        form.ShowDialog()
        return bool(form.saved)
    except Exception as e:
        print("Error showing CTS defaults dialog: " + str(e))
        return False



class CompareResultsForm(Form if Form is not None else object):
    CLOSE = "close"
    IMPORT = "import"
    EXPORT = "export"

    def __init__(self, modified, missing_on_disk, new_on_disk, unchanged_count, moved=None):
        self.Text = "cds-text-sync: Compare UI"
        self.Size = Size(780, 560)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.result_action = self.CLOSE
        self.checkboxes = []
        self.tooltip = ToolTip()

        title = Label()
        title.Text = "Differences between CODESYS IDE and .dump\\views"
        title.Location = Point(16, 14)
        title.Size = Size(730, 24)
        title.Font = Font("Segoe UI", 10, FontStyle.Bold)
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = "Checked objects are used by selected import/export. Unchecked objects are left unchanged."
        subtitle.Location = Point(16, 39)
        subtitle.Size = Size(730, 20)
        subtitle.ForeColor = Color.FromArgb(90, 90, 90)
        self.Controls.Add(subtitle)

        self.list_panel = Panel()
        self.list_panel.Location = Point(0, 70)
        self.list_panel.Size = Size(770, 360)
        self.list_panel.AutoScroll = True
        self.Controls.Add(self.list_panel)

        y = 8
        y = self._add_section(y, "Modified", modified or [])
        y = self._add_section(y, "Missing on disk", missing_on_disk or [])
        y = self._add_section(y, "New on disk", new_on_disk or [])
        y = self._add_section(y, "Moved", moved or [])

        summary = Label()
        moved_count = len(moved or [])
        summary.Text = "Modified: {0}   Missing on disk: {1}   New on disk: {2}   Moved: {3}   Unchanged: {4}".format(
            len(modified or []),
            len(missing_on_disk or []),
            len(new_on_disk or []),
            moved_count,
            unchanged_count,
        )
        summary.Location = Point(16, 440)
        summary.Size = Size(730, 22)
        self.Controls.Add(summary)

        btn_all = Button()
        btn_all.Text = "All"
        btn_all.Location = Point(16, 476)
        btn_all.Size = Size(55, 28)
        btn_all.Click += self._select_all
        self.Controls.Add(btn_all)

        btn_none = Button()
        btn_none.Text = "None"
        btn_none.Location = Point(78, 476)
        btn_none.Size = Size(55, 28)
        btn_none.Click += self._select_none
        self.Controls.Add(btn_none)

        btn_import = Button()
        btn_import.Text = "Import Selected"
        btn_import.Location = Point(398, 476)
        btn_import.Size = Size(112, 28)
        btn_import.Click += self._on_import
        self.Controls.Add(btn_import)

        btn_export = Button()
        btn_export.Text = "Export Selected"
        btn_export.Location = Point(518, 476)
        btn_export.Size = Size(112, 28)
        btn_export.Click += self._on_export
        self.Controls.Add(btn_export)

        btn_close = Button()
        btn_close.Text = "Close"
        btn_close.Location = Point(638, 476)
        btn_close.Size = Size(98, 28)
        btn_close.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_close)
        self.CancelButton = btn_close

    def _format_tip(self, text, width=58):
        lines = []
        for paragraph in str(text).split("\n"):
            chunk = paragraph.strip()
            if not chunk:
                lines.append("")
            else:
                lines.extend(textwrap.wrap(chunk, width=width))
        return "\n".join(lines)

    def _set_tip(self, control, text):
        if self.tooltip is not None and text:
            self.tooltip.SetToolTip(control, self._format_tip(text))

    def _item_label(self, item):
        name = item.get("name") or item.get("guid") or "unknown"
        return name

    def _item_path(self, item):
        projection_diff = item.get("projection_diff") or {}
        if self._use_projection_diff(item):
            return projection_diff.get("path") or item.get("view_path") or item.get("path") or ""
        return item.get("view_path") or item.get("path") or ""

    def _use_projection_diff(self, item):
        projection_diff = item.get("projection_diff") or {}
        if not projection_diff:
            return False
        if item.get("projection_conflict") or item.get("projection_changed_paths"):
            return True
        return projection_diff.get("disk_content", "") != projection_diff.get("ide_content", "")

    def _has_diff_content(self, item):
        projection_diff = item.get("projection_diff") or {}
        return bool(
            projection_diff.get("ide_content")
            or projection_diff.get("disk_content")
            or item.get("ide_content")
            or item.get("disk_content")
        )

    def _diff_payload(self, item):
        projection_diff = item.get("projection_diff") or {}
        if self._use_projection_diff(item):
            return {
                "disk_content": projection_diff.get("disk_content", ""),
                "ide_content": projection_diff.get("ide_content", ""),
                "disk_title": "Disk projection (" + (projection_diff.get("path") or "projection") + ")",
                "ide_title": "IDE snapshot projection",
                "path": projection_diff.get("path") or item.get("view_path") or item.get("path") or "",
            }
        return {
            "disk_content": item.get("disk_content", ""),
            "ide_content": item.get("ide_content", ""),
            "disk_title": "Disk XML",
            "ide_title": "IDE snapshot XML",
            "path": item.get("view_path") or item.get("path") or "",
        }

    def _add_section(self, y, title, items):
        if not items:
            return y
        section = Label()
        section.Text = title
        section.Location = Point(16, y)
        section.Size = Size(720, 20)
        section.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.list_panel.Controls.Add(section)
        y += 22

        for item in items:
            checkbox = CheckBox()
            checkbox.Text = self._item_label(item)
            checkbox.Location = Point(30, y)
            checkbox.Size = Size(580, 22)
            checkbox.Checked = True
            checkbox.Tag = item
            self._set_tip(checkbox, "GUID: {0}\nType: {1}\nPath: {2}".format(
                item.get("guid", ""),
                item.get("type_guid", ""),
                self._item_path(item),
            ))
            self.list_panel.Controls.Add(checkbox)
            self.checkboxes.append(checkbox)

            if self._has_diff_content(item):
                projection_diff = item.get("projection_diff") or {}
                diff_button = Button()
                diff_button.Text = "Diff " + str(projection_diff.get("format") or "") if self._use_projection_diff(item) else "Diff"
                diff_button.Location = Point(650, y - 1)
                diff_button.Size = Size(54, 23)
                diff_button.Tag = item
                diff_button.Click += self._on_diff
                base_tip = "Open side-by-side projection diff for this object." if self._use_projection_diff(item) else "Open side-by-side disk vs IDE diff for this object."
                self._set_tip(diff_button, base_tip + " Hold Ctrl while clicking to save both versions into the .diff folder.")
                self.list_panel.Controls.Add(diff_button)

            path = self._item_path(item)
            if path:
                path_label = Label()
                path_label.Text = path
                path_label.Location = Point(50, y + 22)
                path_label.Size = Size(650, 20)
                path_label.ForeColor = Color.FromArgb(95, 95, 95)
                path_label.Font = Font("Segoe UI", 8)
                self._set_tip(path_label, path)
                self.list_panel.Controls.Add(path_label)
                y += 44
            else:
                y += 26
        return y + 8

    def _select_all(self, sender, event):
        for checkbox in self.checkboxes:
            checkbox.Checked = True

    def _select_none(self, sender, event):
        for checkbox in self.checkboxes:
            checkbox.Checked = False

    def _on_diff(self, sender, event):
        item = sender.Tag
        if not item:
            return
        try:
            payload = self._diff_payload(item)
            if self._ctrl_pressed():
                self._save_diff_files(item, payload)
                return
            from codesys_runtime import load_hidden_module
            diff_module = load_hidden_module("codesys_ui_diff")
            if diff_module is None or not hasattr(diff_module, "show_diff_dialog"):
                raise RuntimeError("codesys_ui_diff module not available")
            diff_module.show_diff_dialog(
                payload.get("disk_content", ""),
                payload.get("ide_content", ""),
                payload.get("disk_title", "Disk"),
                payload.get("ide_title", "IDE snapshot"),
                item.get("name") or item.get("guid") or "object",
            )
        except Exception as e:
            print("Error opening diff: " + str(e))

    def _ctrl_pressed(self):
        if Control is None or Keys is None:
            return False
        try:
            return (Control.ModifierKeys & Keys.Control) == Keys.Control
        except Exception:
            try:
                return Control.ModifierKeys == Keys.Control
            except Exception:
                return False

    def _safe_filename(self, value):
        text = str(value or "object")
        for char in '<>:"/\\|?*':
            text = text.replace(char, "_")
        return text.strip(" .") or "object"

    def _save_diff_files(self, item, payload):
        disk_content = payload.get("disk_content", "")
        ide_content = payload.get("ide_content", "")
        obj_name = item.get("name") or item.get("guid") or "object"
        rel_path = payload.get("path") or item.get("view_path") or item.get("path") or ""
        ext = os.path.splitext(rel_path)[1] if rel_path else ".xml"
        if not ext:
            ext = ".xml"

        from codesys_utils import load_base_dir
        base_dir, _ = load_base_dir()
        if not base_dir:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        diff_dir = os.path.join(base_dir, ".diff")
        if not os.path.exists(diff_dir):
            os.makedirs(diff_dir)

        safe_name = self._safe_filename(obj_name)
        disk_path = os.path.join(diff_dir, "disk_{0}{1}".format(safe_name, ext))
        ide_path = os.path.join(diff_dir, "ide_{0}{1}".format(safe_name, ext))

        with codecs.open(disk_path, "w", "utf-8") as handle:
            handle.write(disk_content)
        with codecs.open(ide_path, "w", "utf-8") as handle:
            handle.write(ide_content)

        show_toast(
            "Diff Files Saved",
            "Saved versions of '{0}' to {1}".format(obj_name, diff_dir),
            timeout=4000,
        )

    def _on_import(self, sender, event):
        self.result_action = self.IMPORT
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_export(self, sender, event):
        self.result_action = self.EXPORT
        self.DialogResult = DialogResult.OK
        self.Close()

    def get_selected(self):
        selected = []
        for checkbox in self.checkboxes:
            if checkbox.Checked and checkbox.Tag:
                selected.append(checkbox.Tag)
        return selected


def show_compare_dialog(different, new_in_ide, new_on_disk, unchanged_count, moved=None):
    if Form is None:
        message = "Modified: {0}\nMissing on disk: {1}\nNew on disk: {2}\nUnchanged: {3}".format(
            len(different or []),
            len(new_in_ide or []),
            len(new_on_disk or []),
            unchanged_count,
        )
        if MessageBox is not None:
            MessageBox.Show(message, "cds-text-sync: Compare", MessageBoxButtons.OK, MessageBoxIcon.Information)
        else:
            print(message)
        return "close", []

    form = CompareResultsForm(different, new_in_ide, new_on_disk, unchanged_count, moved)
    result = form.ShowDialog()
    if result == DialogResult.OK:
        return form.result_action, form.get_selected()
    return CompareResultsForm.CLOSE, []

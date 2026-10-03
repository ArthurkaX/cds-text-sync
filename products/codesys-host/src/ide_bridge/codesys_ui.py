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
        Form, Label, Button, CheckBox, RadioButton, Panel, ToolTip,
        FormBorderStyle, FormStartPosition, FlatStyle, ComboBox, TextBox,
        ComboBoxStyle, TabControl, TabPage, Control, Keys, ScrollBars
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
    RadioButton = None
    Panel = None
    ToolTip = None
    ComboBox = None
    TextBox = None
    ComboBoxStyle = None
    TabControl = None
    TabPage = None
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
    """Project options in two tabs: General (per-user) and Project (per project).

    General edits the sparse per-user file, which seeds new projects and holds
    the behavior values a project inherits. Project edits this project's
    ``cds-text-sync.json``; its behavior block is either "Same as General"
    (inherited, greyed and mirroring the General values live) or "Own for this
    project" (pinned in the project file). Saving writes the per-user file
    first, and only when that succeeds hands the project assembly back to the
    caller, which writes the project file.
    """

    LAYOUTS = [
        ("project-view", "Project folder: project-view/"),
        ("root-view", "Root of project"),
    ]

    # name -> checkbox/textbox for the five behavior keys, in the engine's order.
    def __init__(self, current_settings):
        self.Text = "cds-text-sync: Project Options"
        self.Size = Size(680, 880)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.result_settings = None
        self.result_pinned = None
        self.result_user_defaults = None

        self._base_settings = dict(current_settings)
        self._general_state = settings_layers_model.general_state()
        self.view_root_locked = bool(current_settings.get("_view_root_locked"))
        self.sync_mode_locked = bool(current_settings.get("_sync_mode_locked"))
        self.initial_layout = current_settings.get("layout") or "project-view"
        self.initial_view_root = current_settings.get("view_root") or None
        self.initial_sync_mode = (
            current_settings.get("_sync_mode_lock_value")
            if self.sync_mode_locked
            else current_settings.get("sync_mode")
        ) or "xml_first"

        sources = current_settings.get("_sources")
        if sources is None:
            # No layer read was handed over: treat every behavior key as owned
            # by the project, so the controls stay editable exactly as before.
            sources = dict(
                (name, "project")
                for name in settings_layers_model.behavior_names()
            )
        self._mode = settings_layers_model.behavior_mode(current_settings, sources)

        # Per-tab control registries, keyed by setting name, plus the state of
        # each tab's pair of derived-view lists.
        self._general_behavior = {}
        self._project_behavior = {}
        self._general_lists = None
        self._project_lists = None

        self._build_header()

        self.tabs = TabControl()
        self.tabs.Location = Point(20, 74)
        self.tabs.Size = Size(640, 700)
        self.tab_general = TabPage()
        self.tab_general.Text = "General"
        self.tab_general.BackColor = Color.FromArgb(250, 250, 250)
        self.tab_project = TabPage()
        self.tab_project.Text = "Project"
        self.tab_project.BackColor = Color.FromArgb(250, 250, 250)
        self.tabs.Controls.Add(self.tab_general)
        self.tabs.Controls.Add(self.tab_project)
        self.Controls.Add(self.tabs)

        self._build_general_tab(current_settings)
        self._build_project_tab(current_settings)
        self._build_dialog_buttons()

        self.tabs.SelectedIndex = 1
        self._refresh_project_behavior_state()
        self._refresh_view_root_state()
        self._refresh_view_root_summary()
        self._refresh_view_lists(self._project_lists, self._project_text_first())
        self._refresh_view_lists(self._general_lists, self._general_text_first())

    # -- small builders ---------------------------------------------------

    def _make_label(self, text, x, y, width, height=20, size=9, bold=False,
                    grey=False, red=False):
        label = Label()
        label.Text = text
        label.Location = Point(x, y)
        label.Size = Size(width, height)
        if bold:
            label.Font = Font("Segoe UI", size, FontStyle.Bold)
        elif size != 9:
            label.Font = Font("Segoe UI", size)
        if grey:
            label.ForeColor = Color.FromArgb(110, 110, 110)
        if red:
            label.ForeColor = Color.FromArgb(160, 40, 40)
        return label

    def _make_heading(self, text, x, y, width=360):
        return self._make_label(text, x, y, width, 20, size=9, bold=True)

    def _make_layout_combo(self, value, enabled=True):
        combo = ComboBox()
        combo.DropDownStyle = ComboBoxStyle.DropDownList
        combo.Size = Size(300, 24)
        for _layout_id, layout_label in self.LAYOUTS:
            combo.Items.Add(layout_label)
        index = 0
        for position, (layout_id, _label) in enumerate(self.LAYOUTS):
            if layout_id == value:
                index = position
                break
        combo.SelectedIndex = index
        combo.Enabled = enabled
        return combo

    def _profile_ids(self, current):
        profiles = self._base_settings.get("_available_profiles") or []
        ids = []
        for profile in profiles:
            profile_id = profile.get("id") or profile.get("name")
            if profile_id and profile_id not in ids:
                ids.append(profile_id)
        if current and current not in ids:
            ids.insert(0, current)
        return ids

    def _make_profile_combo(self, value):
        combo = ComboBox()
        combo.DropDownStyle = ComboBoxStyle.DropDownList
        combo.Size = Size(300, 24)
        ids = self._profile_ids(value)
        for profile_id in ids:
            combo.Items.Add(profile_id)
        combo.SelectedIndex = ids.index(value) if value in ids else 0
        return combo

    def _selected_layout(self, combo):
        index = combo.SelectedIndex
        if index < 0 or index >= len(self.LAYOUTS):
            return "project-view"
        return self.LAYOUTS[index][0]

    def _selected_profile(self, combo):
        return str(combo.SelectedItem) or "default"

    def _select_combo_value(self, combo, value):
        items = [str(combo.Items[index]) for index in range(combo.Items.Count)]
        if value not in items:
            combo.Items.Add(value)
            items.append(value)
        combo.SelectedIndex = items.index(value)

    def _build_view_lists(self, parent, y, current_settings, projections, kinds,
                          strict=False):
        """Build the tab's pair of derived-view lists and return their state.

        The two panels share a spot: only the one matching the tab's sync mode
        is shown, the other keeps its checkboxes (and their values) hidden.
        ``strict`` seeds a projection box from the given value alone (the
        General tab, where a built-in default must not look like a choice);
        otherwise the profile's own default applies, as the project tab has
        always done.
        """
        state = {}
        state["label"] = self._make_label("Derived views", 16, y, 120, 20)
        parent.Controls.Add(state["label"])

        projection_panel = Panel()
        projection_panel.Location = Point(140, y - 4)
        projection_panel.Size = Size(420, 118)
        projection_panel.BackColor = Color.White
        parent.Controls.Add(projection_panel)
        state["projection_panel"] = projection_panel
        state["projection_controls"] = []
        options = current_settings.get("_available_projections") or []
        if not options:
            projection_panel.Controls.Add(self._make_label(
                "No optional projections in selected profile.",
                8, 8, 380, 20, size=8, grey=True))
        else:
            offset = 6
            for projection in options:
                checkbox = CheckBox()
                checkbox.Text = (
                    projection.get("label")
                    or projection.get("id")
                    or projection.get("kind")
                    or "projection"
                )
                checkbox.Location = Point(8, offset)
                checkbox.Size = Size(390, 22)
                if strict:
                    checkbox.Checked = settings_layers_model.projection_enabled(
                        projections, projection
                    )
                else:
                    checkbox.Checked = self._projection_enabled(
                        {"projections": projections}, projection
                    )
                checkbox.Tag = projection
                projection_panel.Controls.Add(checkbox)
                state["projection_controls"].append(checkbox)
                offset += 24

        xml_panel = Panel()
        xml_panel.Location = Point(140, y - 4)
        xml_panel.Size = Size(420, 118)
        xml_panel.AutoScroll = True
        xml_panel.BackColor = Color.White
        parent.Controls.Add(xml_panel)
        state["xml_panel"] = xml_panel
        state["xml_controls"] = []
        selected = [str(kind).strip().lower() for kind in (kinds or [])]
        kind_options = current_settings.get("_available_xml_in_view_kinds") or []
        if not kind_options:
            xml_panel.Controls.Add(self._make_label(
                "No XML-only kinds in selected profile.",
                8, 8, 380, 20, size=8, grey=True))
        else:
            offset = 6
            for kind in kind_options:
                checkbox = CheckBox()
                checkbox.Text = kind
                checkbox.Location = Point(8, offset)
                checkbox.Size = Size(390, 22)
                checkbox.Checked = str(kind).strip().lower() in selected
                checkbox.Tag = kind
                xml_panel.Controls.Add(checkbox)
                state["xml_controls"].append(checkbox)
                offset += 24

        state["hint"] = self._make_label("", 140, y + 118, 420, 20, size=8, grey=True)
        parent.Controls.Add(state["hint"])
        return state

    def _refresh_view_lists(self, state, text_first):
        if not state:
            return
        state["projection_panel"].Visible = not text_first
        state["xml_panel"].Visible = text_first
        if text_first:
            state["label"].Text = "Keep XML in view"
            state["hint"].Text = (
                "These kinds keep their native .xml in the view; every other "
                "kind's XML moves to the .dump/xml mirror."
            )
        else:
            state["label"].Text = "Derived views"
            state["hint"].Text = (
                "Enabled .st views own text on disk; XML is rehydrated internally."
            )

    def _apply_view_values(self, state, values):
        projections = values.get("projections")
        if isinstance(projections, dict):
            for checkbox in state["projection_controls"]:
                if checkbox.Tag:
                    checkbox.Checked = settings_layers_model.projection_enabled(
                        projections, checkbox.Tag
                    )
        kinds = values.get("xml_in_view_kinds")
        if isinstance(kinds, (list, tuple)):
            wanted = [str(kind).strip().lower() for kind in kinds]
            for checkbox in state["xml_controls"]:
                checkbox.Checked = str(checkbox.Tag).strip().lower() in wanted

    def _projection_id(self, projection):
        return projection.get("id") or projection.get("kind")

    def _projection_entry(self, projection):
        return {
            "enabled": True,
            "kind": projection.get("kind"),
            "format": projection.get("format"),
            "import_safe": bool(projection.get("import_safe", False)),
        }

    def _selected_projections(self, controls):
        selected = {}
        for checkbox in controls:
            if not checkbox.Checked or not checkbox.Tag:
                continue
            projection_id = self._projection_id(checkbox.Tag)
            if not projection_id:
                continue
            selected[projection_id] = self._projection_entry(checkbox.Tag)
        return selected

    def _checked_projection_ids(self, controls):
        checked = []
        for checkbox in controls:
            if checkbox.Checked and checkbox.Tag:
                projection_id = self._projection_id(checkbox.Tag)
                if projection_id and projection_id not in checked:
                    checked.append(projection_id)
        return checked

    def _selected_kinds(self, controls):
        selected = []
        for checkbox in controls:
            if checkbox.Checked and checkbox.Tag:
                selected.append(str(checkbox.Tag).strip().lower())
        return selected

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

    # -- behavior controls ------------------------------------------------

    def _build_behavior_controls(self, parent, y, controls, mirror):
        """Build the five behavior controls into *parent* at *y*.

        ``mirror`` wires the General tab's controls, so an edit there updates
        the greyed Project controls live while the radio says "Same as General".
        """
        backup = CheckBox()
        backup.Text = "Backup before import"
        backup.Location = Point(140, y)
        backup.Size = Size(300, 22)
        parent.Controls.Add(backup)
        controls["pre_import_backup_enabled"] = backup

        parent.Controls.Add(self._make_label("Max backups", 140, y + 28, 110, 20))
        retention = TextBox()
        retention.Location = Point(254, y + 25)
        retention.Size = Size(50, 22)
        parent.Controls.Add(retention)
        controls["backup_retention_count"] = retention

        entries = [
            ("verbose_logging", "Save detailed engine logs in .dump", y + 54),
            ("advanced_debug", "Advanced debug: also log IDE script messages", y + 80),
            ("show_completion_popup", "Show completion summary after import/export", y + 106),
        ]
        for name, text, top in entries:
            checkbox = CheckBox()
            checkbox.Text = text
            checkbox.Location = Point(140, top)
            checkbox.Size = Size(430, 22)
            parent.Controls.Add(checkbox)
            controls[name] = checkbox

        if mirror:
            backup.CheckedChanged += self._make_general_behavior_handler(
                "pre_import_backup_enabled")
            retention.TextChanged += self._make_general_behavior_handler(
                "backup_retention_count")
            for name, _text, _top in entries:
                controls[name].CheckedChanged += self._make_general_behavior_handler(name)

    def _make_general_behavior_handler(self, name):
        def _handler(sender, event):
            self._on_general_behavior_changed(name)
        return _handler

    def _read_behavior(self, controls, name):
        control = controls.get(name)
        if control is None:
            return None
        if name == "backup_retention_count":
            try:
                value = int(str(control.Text).strip())
                if value >= 1:
                    return value
            except Exception:
                pass
            return 10
        return bool(control.Checked)

    def _write_behavior(self, controls, name, value):
        control = controls.get(name)
        if control is None:
            return
        if name == "backup_retention_count":
            control.Text = str(value if value is not None else 10)
        else:
            control.Checked = bool(value)

    def _apply_behavior_values(self, controls, values):
        for name in settings_layers_model.behavior_names():
            if name in values:
                self._write_behavior(controls, name, values[name])

    def _set_behavior_enabled(self, controls, enabled):
        for control in controls.values():
            control.Enabled = enabled

    def _project_behavior_mode(self):
        if getattr(self, "rb_own", None) is not None and self.rb_own.Checked:
            return settings_layers_model.BEHAVIOR_MODE_OWN
        return settings_layers_model.BEHAVIOR_MODE_SAME

    def _refresh_project_behavior_state(self):
        """Grey or enable the Project behavior block to match the radio.

        On "Same as General" the block mirrors the General tab's current values
        and is disabled; on "Own" the controls are editable and hold whatever
        they held, so switching Same -> Own keeps the shown values.
        """
        if self._project_behavior_mode() == settings_layers_model.BEHAVIOR_MODE_SAME:
            for name in settings_layers_model.behavior_names():
                self._write_behavior(
                    self._project_behavior, name,
                    self._read_behavior(self._general_behavior, name),
                )
            self._set_behavior_enabled(self._project_behavior, False)
        else:
            self._set_behavior_enabled(self._project_behavior, True)

    def _on_behavior_mode_changed(self, sender, event):
        self._refresh_project_behavior_state()

    def _on_general_behavior_changed(self, name):
        if self._project_behavior_mode() != settings_layers_model.BEHAVIOR_MODE_SAME:
            return
        self._write_behavior(
            self._project_behavior, name,
            self._read_behavior(self._general_behavior, name),
        )

    # -- tabs -------------------------------------------------------------

    def _build_header(self):
        title = Label()
        title.Text = "Sync Options"
        title.Font = Font("Segoe UI", 14, FontStyle.Bold)
        title.Location = Point(20, 16)
        title.Size = Size(500, 28)
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = (
            "General applies to every project on this computer; Project is saved "
            "to this project's cds-text-sync.json."
        )
        subtitle.Font = Font("Segoe UI", 9)
        subtitle.ForeColor = Color.FromArgb(90, 90, 90)
        subtitle.Location = Point(22, 46)
        subtitle.Size = Size(620, 22)
        self.Controls.Add(subtitle)

    def _build_general_tab(self, current_settings):
        page = self.tab_general
        path, rows, status, error = self._general_state
        values = dict((row["name"], row["value"]) for row in rows)

        page.Controls.Add(self._make_label(
            "All projects on this computer", 16, 12, 520, 26, size=12, bold=True))
        page.Controls.Add(self._make_label(path, 18, 40, 590, 18, size=8, grey=True))
        if status == "invalid" and error:
            page.Controls.Add(self._make_label(
                "Defaults file could not be read: " + error,
                18, 58, 590, 34, size=8, red=True))

        page.Controls.Add(self._make_heading("New projects start with", 16, 94))

        page.Controls.Add(self._make_label("View storage", 16, 122, 120, 20))
        self.cmb_general_layout = self._make_layout_combo(values.get("layout"))
        self.cmb_general_layout.Location = Point(140, 119)
        page.Controls.Add(self.cmb_general_layout)
        page.Controls.Add(self._make_label(
            "Choose where generated views live by default for new projects.",
            140, 145, 430, 18, size=8, grey=True))

        page.Controls.Add(self._make_label("Profile", 16, 172, 120, 20))
        self.cmb_general_profile = self._make_profile_combo(
            values.get("profile") or "default")
        self.cmb_general_profile.Location = Point(140, 169)
        page.Controls.Add(self.cmb_general_profile)

        page.Controls.Add(self._make_label("Sync mode", 16, 204, 120, 20))
        self.chk_general_text_first = CheckBox()
        self.chk_general_text_first.Text = (
            "Text-first mode (.st files are the source of truth)")
        self.chk_general_text_first.Location = Point(140, 200)
        self.chk_general_text_first.Size = Size(430, 22)
        self.chk_general_text_first.Checked = values.get("sync_mode") == "text_first"
        self.chk_general_text_first.CheckedChanged += self._on_general_text_first_changed
        page.Controls.Add(self.chk_general_text_first)
        page.Controls.Add(self._make_label(
            "Text-first hides native XML in .dump/xml and ST files drive import.",
            140, 224, 440, 18, size=8, grey=True))

        self._general_lists = self._build_view_lists(
            page, 258, current_settings,
            values.get("projections"), values.get("xml_in_view_kinds"), strict=True)

        page.Controls.Add(self._make_heading("Behavior", 16, 402))
        self._build_behavior_controls(page, 428, self._general_behavior, True)
        self._apply_behavior_values(self._general_behavior, values)

        # What the tab opened with: the effective values and the control state
        # they produced. Only a control that differs from this is an edit.
        self._general_originals = values
        self._general_initials = self._read_general_controls()

        btn_reset = Button()
        btn_reset.Text = "Reset to built-in"
        btn_reset.Location = Point(16, 568)
        btn_reset.Size = Size(150, 28)
        btn_reset.Click += self._on_reset_general
        page.Controls.Add(btn_reset)

    def _build_project_tab(self, current_settings):
        page = self.tab_project
        project_name = current_settings.get("_project_name") or "this project"
        project_path = current_settings.get("_settings_path") or "cds-text-sync.json"

        page.Controls.Add(self._make_label(
            "This project: " + str(project_name), 16, 12, 520, 26,
            size=12, bold=True))
        page.Controls.Add(self._make_label(
            project_path + "  (in git)", 18, 40, 590, 18, size=8, grey=True))

        page.Controls.Add(self._make_heading("Format", 16, 72))

        page.Controls.Add(self._make_label("View storage", 16, 100, 120, 20))
        self.cmb_layout = self._make_layout_combo(
            current_settings.get("layout"), enabled=not self.view_root_locked)
        self.cmb_layout.Location = Point(140, 97)
        self.cmb_layout.SelectedIndexChanged += self._on_layout_changed
        page.Controls.Add(self.cmb_layout)
        if self.view_root_locked:
            layout_help = "Folder choice is locked after first export."
        else:
            layout_help = "Choose where generated views live by default."
        page.Controls.Add(self._make_label(
            layout_help, 140, 123, 430, 18, size=8, grey=True))

        self.chk_custom_view_root = CheckBox()
        self.chk_custom_view_root.Text = "Use custom view root"
        self.chk_custom_view_root.Location = Point(140, 148)
        self.chk_custom_view_root.Size = Size(200, 22)
        self.chk_custom_view_root.Checked = bool(current_settings.get("view_root"))
        self.chk_custom_view_root.CheckedChanged += self._on_custom_view_root_changed
        self.chk_custom_view_root.Enabled = not self.view_root_locked
        page.Controls.Add(self.chk_custom_view_root)

        self.txt_view_root = TextBox()
        self.txt_view_root.Location = Point(348, 149)
        self.txt_view_root.Size = Size(220, 22)
        self.txt_view_root.Text = current_settings.get("view_root") or ""
        self.txt_view_root.Enabled = (
            bool(current_settings.get("view_root")) and not self.view_root_locked
        )
        self.txt_view_root.TextChanged += self._on_view_root_changed
        page.Controls.Add(self.txt_view_root)

        self.lbl_view_root_mode = self._make_label(
            "", 140, 174, 430, 34, size=8, grey=True)
        page.Controls.Add(self.lbl_view_root_mode)

        page.Controls.Add(self._make_label("Profile", 16, 218, 120, 20))
        self.cmb_profile = self._make_profile_combo(
            current_settings.get("profile") or "default")
        self.cmb_profile.Location = Point(140, 215)
        page.Controls.Add(self.cmb_profile)

        page.Controls.Add(self._make_label("Sync mode", 16, 248, 120, 20))
        self.chk_text_first = CheckBox()
        self.chk_text_first.Text = "Text-first mode (.st files are the source of truth)"
        self.chk_text_first.Location = Point(140, 244)
        self.chk_text_first.Size = Size(430, 22)
        self.chk_text_first.Checked = self.initial_sync_mode == "text_first"
        self.chk_text_first.Enabled = not self.sync_mode_locked
        self.chk_text_first.CheckedChanged += self._on_text_first_changed
        page.Controls.Add(self.chk_text_first)
        if self.sync_mode_locked:
            sync_help = (
                "Mode is fixed at initialization. To switch, initialize a new "
                "empty sync folder."
            )
        else:
            sync_help = (
                "Choose before the first export. Text-first hides native XML in "
                ".dump/xml and ST files drive import."
            )
        page.Controls.Add(self._make_label(
            sync_help, 140, 268, 440, 30, size=8, grey=True))

        self._project_lists = self._build_view_lists(
            page, 308, current_settings,
            current_settings.get("projections"),
            current_settings.get("xml_in_view_kinds"))

        page.Controls.Add(self._make_heading("Behavior", 16, 452))

        self.rb_same = RadioButton()
        self.rb_same.Text = "Same as General"
        self.rb_same.Location = Point(140, 478)
        self.rb_same.Size = Size(180, 22)
        self.rb_same.Checked = self._mode == settings_layers_model.BEHAVIOR_MODE_SAME
        self.rb_same.CheckedChanged += self._on_behavior_mode_changed
        page.Controls.Add(self.rb_same)

        self.rb_own = RadioButton()
        self.rb_own.Text = "Own for this project"
        self.rb_own.Location = Point(330, 478)
        self.rb_own.Size = Size(200, 22)
        self.rb_own.Checked = self._mode == settings_layers_model.BEHAVIOR_MODE_OWN
        self.rb_own.CheckedChanged += self._on_behavior_mode_changed
        page.Controls.Add(self.rb_own)

        self._build_behavior_controls(page, 506, self._project_behavior, False)
        for name in settings_layers_model.behavior_names():
            self._write_behavior(
                self._project_behavior, name, current_settings.get(name))

        self.chk_gitignore = CheckBox()
        self.chk_gitignore.Text = "Add recommended .gitignore entries"
        self.chk_gitignore.Location = Point(140, 642)
        self.chk_gitignore.Size = Size(430, 22)
        self.chk_gitignore.Checked = bool(current_settings.get("_ensure_gitignore", False))
        page.Controls.Add(self.chk_gitignore)

    def _build_dialog_buttons(self):
        btn_ok = Button()
        btn_ok.Text = "Save"
        btn_ok.Location = Point(444, 790)
        btn_ok.Size = Size(85, 28)
        btn_ok.Click += self._on_save
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Location = Point(536, 790)
        btn_cancel.Size = Size(85, 28)
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

    # -- view root and sync mode -----------------------------------------

    def _refresh_view_root_state(self):
        if self.txt_view_root is not None and self.chk_custom_view_root is not None:
            self.txt_view_root.Enabled = (
                bool(self.chk_custom_view_root.Checked) and not self.view_root_locked
            )

    def _refresh_view_root_summary(self):
        if self.lbl_view_root_mode is None:
            return
        if self.view_root_locked:
            locked_value = self.initial_view_root
            if locked_value:
                self.lbl_view_root_mode.Text = (
                    "Locked path: custom view root = {0}".format(locked_value))
            elif self.initial_layout == "root-view":
                self.lbl_view_root_mode.Text = "Locked path: sync root"
            else:
                self.lbl_view_root_mode.Text = "Locked path: project-view/"
            return
        layout_value = self._selected_layout(self.cmb_layout)
        if layout_value == "project-view":
            default_text = "Default: project-view/"
        else:
            default_text = "Default: sync root"

        custom_path = self.txt_view_root.Text.strip()
        if self.chk_custom_view_root.Checked and custom_path:
            self.lbl_view_root_mode.Text = (
                "Active path: custom view root = {0}".format(custom_path))
        elif self.chk_custom_view_root.Checked:
            self.lbl_view_root_mode.Text = (
                "Custom view root is enabled, but the path is empty.")
        else:
            self.lbl_view_root_mode.Text = default_text

    def _on_layout_changed(self, sender, event):
        self._refresh_view_root_summary()

    def _on_custom_view_root_changed(self, sender, event):
        self._refresh_view_root_state()
        self._refresh_view_root_summary()

    def _on_view_root_changed(self, sender, event):
        self._refresh_view_root_summary()

    def _general_text_first(self):
        return bool(self.chk_general_text_first.Checked)

    def _project_text_first(self):
        if self.sync_mode_locked:
            return self.initial_sync_mode == "text_first"
        return bool(self.chk_text_first.Checked)

    def _on_general_text_first_changed(self, sender, event):
        self._refresh_view_lists(self._general_lists, self._general_text_first())

    def _on_text_first_changed(self, sender, event):
        self._refresh_view_lists(self._project_lists, self._project_text_first())

    # -- saving -----------------------------------------------------------

    def _read_general_scalars(self):
        return {
            "layout": self._selected_layout(self.cmb_general_layout),
            "profile": self._selected_profile(self.cmb_general_profile),
            "sync_mode": "text_first" if self._general_text_first() else "xml_first",
            "pre_import_backup_enabled": self._read_behavior(
                self._general_behavior, "pre_import_backup_enabled"),
            "backup_retention_count": self._read_behavior(
                self._general_behavior, "backup_retention_count"),
            "verbose_logging": self._read_behavior(
                self._general_behavior, "verbose_logging"),
            "advanced_debug": self._read_behavior(
                self._general_behavior, "advanced_debug"),
            "show_completion_popup": self._read_behavior(
                self._general_behavior, "show_completion_popup"),
        }

    def _read_general_controls(self):
        """The General tab's whole control state, in the shape the model wants."""
        state = self._read_general_scalars()
        state["kinds_checked"] = self._selected_kinds(
            self._general_lists["xml_controls"])
        state["projections_checked"] = self._checked_projection_ids(
            self._general_lists["projection_controls"])
        return state

    def _general_values_to_store(self):
        """Assemble the General values to write from the controls.

        The model keeps everything the user did not touch at the effective
        value the tab opened with, so pressing Save on an untouched tab
        rewrites the same sparse file (a first save writes just the version).
        """
        return settings_layers_model.general_values_to_store(
            self._general_originals,
            self._general_initials,
            self._read_general_controls(),
            self._base_settings.get("_available_projections") or [],
            self._selected_projections(self._general_lists["projection_controls"]),
        )

    def _on_reset_general(self, sender, event):
        """Fill the General controls from the built-in defaults; nothing is saved."""
        self._apply_general_values(settings_layers_model.reset_user_rows())

    def _apply_general_values(self, values):
        layout = values.get("layout")
        if layout:
            for position, (layout_id, _label) in enumerate(self.LAYOUTS):
                if layout_id == layout:
                    self.cmb_general_layout.SelectedIndex = position
                    break
        profile = values.get("profile")
        if profile:
            self._select_combo_value(self.cmb_general_profile, profile)
        self.chk_general_text_first.Checked = values.get("sync_mode") == "text_first"
        self._apply_view_values(self._general_lists, values)
        self._apply_behavior_values(self._general_behavior, values)

    def _show_error(self, title, message):
        if MessageBox is not None:
            MessageBox.Show(
                message, title, MessageBoxButtons.OK, MessageBoxIcon.Warning)
        else:
            print(title + ": " + message)

    def _on_save(self, sender, event):
        # General first: the project file must inherit whatever it just wrote,
        # and a failure here has to stop the project write.
        written, error = settings_layers_model.save_user_defaults(
            self._general_values_to_store())
        if error:
            self._show_error("Cannot save your defaults", error)
            return
        self.result_user_defaults = written

        if self.view_root_locked:
            layout_value = self.initial_layout
            view_root_value = self.initial_view_root
        else:
            layout_value = self._selected_layout(self.cmb_layout)
            view_root_value = None
            if self.chk_custom_view_root.Checked:
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
            "profile": self._selected_profile(self.cmb_profile),
            "projections": self._selected_projections(
                self._project_lists["projection_controls"]),
            "sync_mode": sync_mode_value,
            "xml_in_view_kinds": self._selected_kinds(
                self._project_lists["xml_controls"]),
        }
        behavior_values = {}
        for name in settings_layers_model.behavior_names():
            behavior_values[name] = self._read_behavior(self._project_behavior, name)
        settings, pinned = settings_layers_model.assemble_project_save(
            self._base_settings, format_values, behavior_values,
            self._project_behavior_mode(),
        )
        settings["_ensure_gitignore"] = bool(self.chk_gitignore.Checked)
        settings["_pinned_behavior"] = pinned
        self.result_settings = settings
        self.result_pinned = pinned
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

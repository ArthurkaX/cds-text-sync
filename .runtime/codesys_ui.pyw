# -*- coding: utf-8 -*-
"""
codesys_ui.pyw - Minimal UI helpers for active XML-first commands.
"""
from __future__ import print_function
import codecs
import os
import textwrap

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult,
        Form, Label, Button, CheckBox, Panel, ToolTip, FormBorderStyle,
        FormStartPosition, FlatStyle, ComboBox, TextBox, ComboBoxStyle,
        Control, Keys
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


class DirectoryChoiceForm(Form if Form is not None else object):
    """Legacy-style choice dialog for setting the sync directory."""

    def __init__(self, title, message):
        self.Text = title
        self.Size = Size(450, 270)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.choice = "cancel"

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


def show_directory_choice_dialog(title, message):
    if Form is not None:
        try:
            form = DirectoryChoiceForm(title, message)
            form.ShowDialog()
            return form.choice
        except Exception as e:
            print("Error showing directory dialog: " + str(e))
    return ask_yes_no_cancel(title, message)


def show_toast(title, message, timeout=3000):
    print("%s: %s" % (title, message))


class ProjectOptionsForm(Form if Form is not None else object):
    LAYOUTS = [
        ("project-view", "Project folder: project-view/"),
        ("root-view", "Root of project"),
    ]

    def __init__(self, current_settings):
        self.Text = "cds-text-sync: Project Options"
        self.Size = Size(580, 650)
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(250, 250, 250)
        self.result_settings = None
        self.projection_controls = []
        self.view_root_locked = bool(current_settings.get("_view_root_locked"))
        self.initial_layout = current_settings.get("layout") or "project-view"
        self.initial_view_root = current_settings.get("view_root") or None

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
        self.cmb_profile.SelectedIndex = profile_ids.index(current_profile) if current_profile in profile_ids else 0
        self.Controls.Add(self.cmb_profile)

        lbl_projections = Label()
        lbl_projections.Text = "Derived views"
        lbl_projections.Location = Point(24, 290)
        lbl_projections.Size = Size(120, 20)
        self.Controls.Add(lbl_projections)

        self.projections_panel = Panel()
        self.projections_panel.Location = Point(150, 286)
        self.projections_panel.Size = Size(360, 118)
        self.projections_panel.AutoScroll = False
        self.projections_panel.BackColor = Color.White
        self.Controls.Add(self.projections_panel)
        self._add_projection_options(current_settings)

        projection_hint = Label()
        projection_hint.Text = "Enabled .st views own text on disk; XML is rehydrated internally."
        projection_hint.Location = Point(150, 410)
        projection_hint.Size = Size(340, 20)
        projection_hint.ForeColor = Color.FromArgb(110, 110, 110)
        projection_hint.Font = Font("Segoe UI", 8)
        self.Controls.Add(projection_hint)

        lbl_backup = Label()
        lbl_backup.Text = "Safety backup"
        lbl_backup.Location = Point(24, 440)
        lbl_backup.Size = Size(120, 20)
        self.Controls.Add(lbl_backup)

        self.chk_pre_import_backup = CheckBox()
        self.chk_pre_import_backup.Text = "Backup before import"
        self.chk_pre_import_backup.Location = Point(150, 436)
        self.chk_pre_import_backup.Size = Size(190, 22)
        self.chk_pre_import_backup.Checked = bool(current_settings.get("pre_import_backup_enabled", True))
        self.Controls.Add(self.chk_pre_import_backup)

        lbl_retention = Label()
        lbl_retention.Text = "Max backups"
        lbl_retention.Location = Point(350, 440)
        lbl_retention.Size = Size(82, 20)
        self.Controls.Add(lbl_retention)

        self.txt_backup_retention = TextBox()
        self.txt_backup_retention.Location = Point(436, 437)
        self.txt_backup_retention.Size = Size(42, 22)
        self.txt_backup_retention.Text = str(current_settings.get("backup_retention_count", 10))
        self.Controls.Add(self.txt_backup_retention)

        backup_hint = Label()
        backup_hint.Text = "Timestamped project binaries are written to .backup/ before IDE changes."
        backup_hint.Location = Point(150, 463)
        backup_hint.Size = Size(360, 20)
        backup_hint.ForeColor = Color.FromArgb(110, 110, 110)
        backup_hint.Font = Font("Segoe UI", 8)
        self.Controls.Add(backup_hint)

        self.chk_verbose_logging = CheckBox()
        self.chk_verbose_logging.Text = "Save detailed engine logs in .dump"
        self.chk_verbose_logging.Location = Point(150, 494)
        self.chk_verbose_logging.Size = Size(300, 22)
        self.chk_verbose_logging.Checked = bool(current_settings.get("verbose_logging", False))
        self.Controls.Add(self.chk_verbose_logging)

        self.chk_gitignore = CheckBox()
        self.chk_gitignore.Text = "Add recommended .gitignore entries"
        self.chk_gitignore.Location = Point(150, 522)
        self.chk_gitignore.Size = Size(310, 22)
        self.chk_gitignore.Checked = bool(current_settings.get("_ensure_gitignore", False))
        self.Controls.Add(self.chk_gitignore)

        btn_ok = Button()
        btn_ok.Text = "Save"
        btn_ok.Location = Point(344, 560)
        btn_ok.Size = Size(85, 28)
        btn_ok.Click += self._on_save
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Location = Point(436, 560)
        btn_cancel.Size = Size(85, 28)
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel
        self._refresh_view_root_state()
        self._refresh_view_root_summary()

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
        self.result_settings = {
            "layout": layout_value,
            "view_root": view_root_value,
            "profile": str(self.cmb_profile.SelectedItem) or "default",
            "projections": self._selected_projections(),
            "verbose_logging": bool(self.chk_verbose_logging.Checked),
            "pre_import_backup_enabled": bool(self.chk_pre_import_backup.Checked),
            "backup_retention_count": self._backup_retention_count(),
            "_ensure_gitignore": bool(self.chk_gitignore.Checked),
        }
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

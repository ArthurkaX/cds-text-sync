# -*- coding: utf-8 -*-
"""WinForms dialogs used by the lightweight CODESYS ``fmt`` command."""
from __future__ import print_function

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, Label, Button, ListBox, RichTextBox, TextBox, MessageBox,
        MessageBoxButtons, MessageBoxIcon, DialogResult, FormBorderStyle,
        FormStartPosition, AnchorStyles, BorderStyle, RichTextBoxScrollBars,
        FlatStyle, DrawMode, DrawItemState, AutoScaleMode
    )
    from System.Drawing import Size, Point, Font, FontStyle, Color, SolidBrush
except Exception:
    Form = None


if Form is not None:
    _BG = Color.FromArgb(30, 30, 30)
    _PANEL = Color.FromArgb(37, 37, 38)
    _TEXT = Color.FromArgb(225, 225, 225)
    _DIM = Color.FromArgb(160, 160, 160)
    _BUTTON_BG = Color.FromArgb(72, 72, 78)
    _BUTTON_BORDER = Color.FromArgb(115, 115, 125)
    _BEFORE = Color.FromArgb(245, 180, 100)
    _AFTER = Color.FromArgb(125, 220, 145)
    _CHANGED_BG = Color.FromArgb(75, 62, 28)
    _ADDED_BG = Color.FromArgb(35, 75, 45)


def _changed_line_sets(before, after):
    left = (before or "").split("\n")
    right = (after or "").split("\n")
    # The formatter never inserts or removes lines.  Comparing by index is
    # deterministic, agrees with the header's changed-line count, and avoids
    # SequenceMatcher.autojunk turning repeated ST lines into one giant diff.
    length = max(len(left), len(right))
    left_changed = {
        index for index in range(length)
        if (left[index] if index < len(left) else "")
        != (right[index] if index < len(right) else "")
    }
    right_changed = set(left_changed)
    return left_changed, right_changed


def _highlight_lines(box, line_numbers, color):
    box.SuspendLayout()
    try:
        for line_number in line_numbers:
            if line_number < 0 or line_number >= box.Lines.Length:
                continue
            start = box.GetFirstCharIndexFromLine(line_number)
            if start < 0:
                continue
            length = len(box.Lines[line_number])
            box.Select(start, length)
            box.SelectionBackColor = color
        box.SelectionStart = 0
        box.SelectionLength = 0
    finally:
        box.ResumeLayout()


class ObjectPickerForm(Form if Form is not None else object):
    def __init__(self, items, selected_index=-1, analyze_callback=None, scan_callback=None):
        self.Text = "FMT - Select object"
        self.Size = Size(980, 660)
        self.MinimumSize = Size(700, 460)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.AutoScaleMode = AutoScaleMode.Font
        self.BackColor = _BG
        self.selected_index = selected_index
        self.action = "cancel"
        self.analyze_callback = analyze_callback
        self.scan_callback = scan_callback
        self.analyzing = False
        self._status = None
        self._visible_indexes = list(range(len(items)))

        title = Label()
        title.Text = "Select a Structured Text object from the project"
        title.ForeColor = _TEXT
        title.Font = Font("Segoe UI", 12, FontStyle.Bold)
        title.Location = Point(16, 14)
        title.AutoSize = True
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = "Select a block to analyze it. FIX all scans from the top and opens the first block that needs changes."
        subtitle.ForeColor = _DIM
        subtitle.Location = Point(18, 45)
        subtitle.AutoSize = True
        self.Controls.Add(subtitle)

        status = Label()
        status.Text = "Select a block to analyze it."
        status.ForeColor = _DIM
        status.Location = Point(18, 63)
        status.AutoSize = True
        self._status = status
        self.Controls.Add(status)

        search = TextBox()
        search.Location = Point(16, 82)
        search.Size = Size(320, 24)
        search.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        search.Text = ""
        search.TextChanged += self._on_filter_changed
        self._search = search
        self.Controls.Add(search)

        self.list = ListBox()
        self.list.Location = Point(16, 114)
        self.list.Size = Size(940, 462)
        self.list.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self.list.BackColor = _PANEL
        self.list.ForeColor = _TEXT
        self.list.Font = Font("Consolas", 10)
        self.list.DrawMode = DrawMode.OwnerDrawFixed
        self.list.ItemHeight = 25
        self.list.DrawItem += self._draw_item
        self.items = items
        self._refresh_list()
        if selected_index in self._visible_indexes:
            self.list.SelectedIndex = self._visible_indexes.index(selected_index)
        self.list.SelectedIndexChanged += self._on_selection_changed
        self.list.DoubleClick += self._accept
        self.Controls.Add(self.list)

        cancel = Button()
        cancel.Text = "Cancel"
        cancel.Size = Size(90, 30)
        cancel.Location = Point(650, 590)
        cancel.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        cancel.DialogResult = DialogResult.Cancel
        self._style_button(cancel)
        self.Controls.Add(cancel)
        self.CancelButton = cancel
        self._cancel_button = cancel

        all_button = Button()
        all_button.Text = "FIX all"
        all_button.Size = Size(100, 30)
        all_button.Location = Point(750, 590)
        all_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        all_button.Click += self._accept_all
        self._style_button(all_button)
        self.Controls.Add(all_button)
        self._all_button = all_button

        selected = Button()
        selected.Text = "Open selected"
        selected.Size = Size(120, 30)
        selected.Location = Point(860, 590)
        selected.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        selected.Click += self._accept
        self._style_button(selected)
        self.Controls.Add(selected)
        self._selected_button = selected
        self.AcceptButton = selected
        self.Resize += self._layout
        self._layout()

    def _style_button(self, button):
        button.BackColor = _BUTTON_BG
        button.ForeColor = _TEXT
        button.FlatStyle = FlatStyle.Flat
        button.FlatAppearance.BorderColor = _BUTTON_BORDER
        button.FlatAppearance.BorderSize = 1
        button.UseVisualStyleBackColor = False

    def _draw_item(self, sender, event):
        if event.Index < 0:
            return
        item = self.items[self._visible_indexes[event.Index]]
        event.DrawBackground()
        selected = bool(event.State & DrawItemState.Selected)
        status = item.get("status")
        if selected:
            color = _TEXT
        elif status == "changed":
            color = _BEFORE
        elif status == "ok":
            color = _AFTER
        else:
            color = _DIM
        brush = SolidBrush(color)
        try:
            suffix = item["display"][len(item["label"]):].strip()
            event.Graphics.DrawString(
                item["label"], self.list.Font, brush,
                event.Bounds.X + 6, event.Bounds.Y + 4
            )
            if suffix:
                suffix_width = event.Graphics.MeasureString(suffix, self.list.Font).Width
                event.Graphics.DrawString(
                    suffix, self.list.Font, brush,
                    event.Bounds.Right - suffix_width - 8, event.Bounds.Y + 4
                )
        finally:
            brush.Dispose()
        event.DrawFocusRectangle()

    def _analyze_index(self, index):
        if self.analyzing or self.analyze_callback is None:
            return
        if index < 0 or index >= len(self.items):
            return
        if self.items[index].get("analysis") is not None:
            return
        self.analyzing = True
        self._status.Text = "Analyzing selected block..."
        self.UseWaitCursor = True
        try:
            self.analyze_callback(index)
            self.list.Invalidate()
        finally:
            self.analyzing = False
            self.UseWaitCursor = False
            status = self.items[index].get("status")
            self._status.Text = (
                "Analysis complete."
                if status in ("changed", "ok")
                else "The block could not be analyzed."
            )

    def _on_selection_changed(self, sender, event):
        if self.list.SelectedIndex >= 0:
            self._analyze_index(self._visible_indexes[self.list.SelectedIndex])

    def _accept(self, sender, event):
        if self.list.SelectedIndex < 0:
            return
        visible = self.list.SelectedIndex
        self._analyze_index(self._visible_indexes[visible])
        self.selected_index = self._visible_indexes[visible]
        self.action = "selected"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _accept_all(self, sender, event):
        if self.scan_callback is None:
            return
        self.analyzing = True
        self._status.Text = "Scanning blocks from the top..."
        self.UseWaitCursor = True
        try:
            index = self.scan_callback(0)
            if index < 0:
                show_message("FMT", "No formatting changes were found.", "info")
                self.list.Invalidate()
                return
            self.selected_index = index
            if index in self._visible_indexes:
                self.list.SelectedIndex = self._visible_indexes.index(index)
            self.action = "all"
            self.DialogResult = DialogResult.OK
            self.Close()
        finally:
            self.analyzing = False
            self.UseWaitCursor = False

    def _layout(self, sender=None, event=None):
        width = self.ClientSize.Width
        height = self.ClientSize.Height
        margin = 16
        gap = 10
        button_y = max(0, height - 42)
        self._search.Location = Point(margin, 82)
        self._search.Size = Size(max(180, width - margin * 2), 24)
        self.list.Location = Point(margin, 114)
        self.list.Size = Size(max(100, width - margin * 2), max(100, button_y - 124))
        right = width - margin
        self._selected_button.Location = Point(right - self._selected_button.Width, button_y)
        right -= self._selected_button.Width + gap
        self._all_button.Location = Point(right - self._all_button.Width, button_y)
        right -= self._all_button.Width + gap
        self._cancel_button.Location = Point(right - self._cancel_button.Width, button_y)

    def _refresh_list(self):
        query = (self._search.Text or "").strip().lower()
        self._visible_indexes = [
            index for index, item in enumerate(self.items)
            if not query or query in item["label"].lower()
        ]
        selected_object = None
        if self.list.SelectedIndex >= 0 and self.list.SelectedIndex < len(self._visible_indexes):
            selected_object = self._visible_indexes[self.list.SelectedIndex]
        self.list.BeginUpdate()
        try:
            self.list.Items.Clear()
            for index in self._visible_indexes:
                self.list.Items.Add(self.items[index]["display"])
        finally:
            self.list.EndUpdate()
        if selected_object in self._visible_indexes:
            self.list.SelectedIndex = self._visible_indexes.index(selected_object)
        elif self.list.Items.Count:
            self.list.SelectedIndex = 0

    def _on_filter_changed(self, sender, event):
        if not hasattr(self, "list"):
            return
        self._refresh_list()
        self.list.Invalidate()


class FmtPreviewForm(Form if Form is not None else object):
    def __init__(self, object_name, before, after, changed_lines):
        self.Text = "FMT Preview - " + (object_name or "Structured Text")
        self.Size = Size(1600, 980)
        self.MinimumSize = Size(1050, 650)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.AutoScaleMode = AutoScaleMode.Font
        self.BackColor = _BG
        self.action = "stop"

        title = Label()
        title.Text = object_name or "Structured Text"
        title.ForeColor = _TEXT
        title.Font = Font("Segoe UI", 12, FontStyle.Bold)
        title.Location = Point(16, 12)
        title.AutoSize = True
        self.Controls.Add(title)

        stats = Label()
        stats.Text = (
            "FMT preview - {0} changed line(s). Changes are applied directly "
            "to the IDE; use Undo if needed. Apply, skip, or stop."
        ).format(changed_lines)
        stats.ForeColor = _DIM
        stats.Location = Point(18, 43)
        stats.AutoSize = True
        self.Controls.Add(stats)

        before_label = Label()
        before_label.Text = "Before"
        before_label.ForeColor = _BEFORE
        before_label.Location = Point(18, 76)
        before_label.AutoSize = True
        self.Controls.Add(before_label)

        after_label = Label()
        after_label.Text = "After"
        after_label.ForeColor = _AFTER
        after_label.Location = Point(800, 76)
        after_label.AutoSize = True
        self.Controls.Add(after_label)
        self._after_label = after_label
        self._changed_left = set()
        self._changed_right = set()
        self._jump_index = -1

        self._before = self._text_box(before)
        self._after = self._text_box(after)
        self._before.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self._after.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(self._before)
        self.Controls.Add(self._after)
        self._before.VScroll += self._sync_scroll
        self._after.VScroll += self._sync_scroll
        self.Resize += self._on_resize

        stop = Button()
        stop.Text = "Stop"
        stop.Size = Size(90, 32)
        stop.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        stop.DialogResult = DialogResult.Cancel
        self._style_button(stop)
        self.Controls.Add(stop)
        self.CancelButton = stop
        self._stop_button = stop

        skip = Button()
        skip.Text = "Skip"
        skip.Size = Size(90, 32)
        skip.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        skip.Click += self._skip
        self._style_button(skip)
        self.Controls.Add(skip)
        self._skip_button = skip

        apply_button = Button()
        apply_button.Text = "Apply"
        apply_button.Size = Size(90, 32)
        apply_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        apply_button.Click += self._apply
        self._style_button(apply_button)
        self.Controls.Add(apply_button)
        self._apply_button = apply_button
        self.AcceptButton = apply_button
        previous = Button()
        previous.Text = "Previous change"
        previous.Size = Size(120, 32)
        previous.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        previous.Click += self._previous_change
        self._style_button(previous)
        self.Controls.Add(previous)
        self._previous_button = previous
        next_button = Button()
        next_button.Text = "Next change"
        next_button.Size = Size(105, 32)
        next_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        next_button.Click += self._next_change
        self._style_button(next_button)
        self.Controls.Add(next_button)
        self._next_button = next_button
        self._layout()
        self._highlight(before, after)

    def _text_box(self, value):
        box = RichTextBox()
        box.Text = value or ""
        box.ReadOnly = True
        box.BackColor = _PANEL
        box.ForeColor = _TEXT
        box.Font = Font("Consolas", 10)
        box.WordWrap = False
        box.BorderStyle = BorderStyle.FixedSingle
        box.ScrollBars = RichTextBoxScrollBars.Both
        box.DetectUrls = False
        return box

    def _highlight(self, before, after):
        left, right = _changed_line_sets(before, after)
        self._changed_left = sorted(left)
        self._changed_right = sorted(right)
        _highlight_lines(self._before, left, _CHANGED_BG)
        _highlight_lines(self._after, right, _ADDED_BG)

    def _style_button(self, button):
        button.BackColor = _BUTTON_BG
        button.ForeColor = _TEXT
        button.FlatStyle = FlatStyle.Flat
        button.FlatAppearance.BorderColor = _BUTTON_BORDER
        button.FlatAppearance.BorderSize = 1
        button.UseVisualStyleBackColor = False

    def _layout(self):
        width = self.ClientSize.Width
        height = self.ClientSize.Height
        left = 16
        gap = 10
        half = (width - left * 2 - gap) // 2
        box_height = max(200, height - 155)
        self._before.Location = Point(left, 100)
        self._before.Size = Size(half, box_height)
        self._after.Location = Point(left + half + gap, 100)
        self._after.Size = Size(half, box_height)
        self._after_label.Location = Point(left + half + gap, 76)
        button_y = max(0, height - 48)
        self._stop_button.Location = Point(width - 16 - self._stop_button.Width, button_y)
        self._skip_button.Location = Point(
            self._stop_button.Left - 10 - self._skip_button.Width, button_y
        )
        self._apply_button.Location = Point(
            self._skip_button.Left - 10 - self._apply_button.Width, button_y
        )
        self._previous_button.Location = Point(left, button_y)
        self._next_button.Location = Point(
            self._previous_button.Right + 8, button_y
        )

    def _on_resize(self, sender, event):
        self._layout()

    def _apply(self, sender, event):
        self.action = "apply"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _skip(self, sender, event):
        self.action = "skip"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _sync_scroll(self, sender, event):
        other = self._after if sender is self._before else self._before
        if getattr(self, "_syncing_scroll", False):
            return
        self._syncing_scroll = True
        try:
            other.SelectionStart = sender.SelectionStart
            other.ScrollToCaret()
        finally:
            self._syncing_scroll = False

    def _jump_change(self, direction):
        changes = self._changed_left
        if not changes:
            return
        if direction > 0:
            candidates = [line for line in changes if line > self._jump_index]
            target = candidates[0] if candidates else changes[0]
        else:
            candidates = [line for line in changes if line < self._jump_index]
            target = candidates[-1] if candidates else changes[-1]
        self._jump_index = target
        for box in (self._before, self._after):
            if target < box.Lines.Length:
                start = box.GetFirstCharIndexFromLine(target)
                box.Select(max(0, start), len(box.Lines[target]))
                box.ScrollToCaret()

    def _previous_change(self, sender, event):
        self._jump_change(-1)

    def _next_change(self, sender, event):
        self._jump_change(1)


def show_object_picker(items, selected_index=-1, analyze_callback=None, scan_callback=None):
    if Form is None:
        return "cancel", -1
    form = ObjectPickerForm(
        items,
        selected_index=selected_index,
        analyze_callback=analyze_callback,
        scan_callback=scan_callback,
    )
    form.ShowDialog()
    return form.action, form.selected_index


def show_fmt_preview(object_name, before, after, changed_lines):
    if Form is None:
        return "stop"
    form = FmtPreviewForm(object_name, before, after, changed_lines)
    form.ShowDialog()
    return form.action


def show_message(title, message, icon="info"):
    if Form is None:
        print("[FMT] " + str(message))
        return
    message_icon = MessageBoxIcon.Information
    if icon == "warning":
        message_icon = MessageBoxIcon.Warning
    elif icon == "error":
        message_icon = MessageBoxIcon.Error
    MessageBox.Show(message, title, MessageBoxButtons.OK, message_icon)

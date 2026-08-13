# -*- coding: utf-8 -*-
"""WinForms dialogs used by the lightweight CODESYS ``fmt`` command."""
from __future__ import print_function

from ide_picker_common import pending_indexes, sort_item_indexes

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, Label, Button, ListBox, RichTextBox, TextBox, MessageBox,
        MessageBoxButtons, MessageBoxIcon, DialogResult, FormBorderStyle,
        FormStartPosition, AnchorStyles, BorderStyle, RichTextBoxScrollBars,
        FlatStyle, DrawMode, DrawItemState, AutoScaleMode, Timer, ToolTip,
        Keys, Cursors
    )
    from System.Drawing import Size, Point, Font, FontStyle, Color, SolidBrush
    from System.Diagnostics import Stopwatch
except Exception:
    Form = None


# Copy strings for the FMT object picker. Plain strings, defined outside the
# CLR guard so they exist even when WinForms is unavailable.
PICKER_LABELS = {
    "title": "FMT - Select object",
    "heading": "Select a Structured Text object from the project",
    "subtitle": "Select a block to analyze it. Review All scans from the top and opens the first block that needs changes.",
    "status": "Select a block to analyze it.",
    "scan_button": "Review All",
    "open_button": "Open selected",
    "scan_status": "Scanning blocks from the top...",
    "scan_none": "No formatting changes were found.",
    "analysis_done": "Analysis complete - {0} block(s) need formatting.",
    "analysis_hits": " {0} need formatting.",
    "message_title": "FMT",
}

# A sweep spends one full ST parse per block on the UI thread, so it is paced
# by a time budget per timer tick rather than one block per tick, and anything
# larger than this has to be confirmed: an unattended sweep over a whole
# project is what made this dialog look hung.
ANALYSIS_BUDGET_MS = 60
ANALYSIS_CONFIRM_LIMIT = 50


# The review wizard opens a new dialog for every changed object.  Keep the
# user-selected geometry at module scope so moving to the next object does not
# make a maximized preview snap back to the default size.
_FMT_PREVIEW_STATE = None


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
    _BEFORE_FOCUS = Color.FromArgb(150, 105, 35)
    _AFTER_FOCUS = Color.FromArgb(55, 125, 70)


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


def _line_by_line_diff(before, after):
    """Render a compact, one-column view of the formatter's line changes.

    Formatting deliberately preserves the number of source lines.  Keeping
    unchanged lines once and placing the old/new forms next to each other in
    the sequence makes a long formatting-only edit easier to scan than two
    distant panes.
    """
    left = (before or "").split("\n")
    right = (after or "").split("\n")
    rendered = []
    removed = set()
    added = set()
    for index in range(max(len(left), len(right))):
        old = left[index].rstrip("\r") if index < len(left) else ""
        new = right[index].rstrip("\r") if index < len(right) else ""
        if old == new:
            rendered.append("  " + old)
            continue
        removed.add(len(rendered))
        rendered.append("- " + old)
        added.add(len(rendered))
        rendered.append("+ " + new)
    return "\n".join(rendered), removed, added


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


def _highlight_span(box, line_number, start, end, color):
    if line_number < 0 or line_number >= box.Lines.Length or end <= start:
        return
    line_start = box.GetFirstCharIndexFromLine(line_number)
    if line_start < 0:
        return
    line_length = len(box.Lines[line_number])
    start = max(0, min(start, line_length))
    end = max(start, min(end, line_length))
    if end <= start:
        return
    box.Select(line_start + start, end - start)
    box.SelectionBackColor = color


def _highlight_changed_characters(before_box, after_box, before, after, lines):
    left_lines = (before or "").split("\n")
    right_lines = (after or "").split("\n")
    before_box.SuspendLayout()
    after_box.SuspendLayout()
    try:
        for line_number in lines:
            left = (
                left_lines[line_number].rstrip("\r")
                if line_number < len(left_lines)
                else ""
            )
            right = (
                right_lines[line_number].rstrip("\r")
                if line_number < len(right_lines)
                else ""
            )
            prefix = 0
            while prefix < len(left) and prefix < len(right) and left[prefix] == right[prefix]:
                prefix += 1
            left_end = len(left)
            right_end = len(right)
            while left_end > prefix and right_end > prefix and left[left_end - 1] == right[right_end - 1]:
                left_end -= 1
                right_end -= 1
            _highlight_span(before_box, line_number, prefix, left_end, _BEFORE_FOCUS)
            _highlight_span(after_box, line_number, prefix, right_end, _AFTER_FOCUS)
    finally:
        before_box.ResumeLayout()
        after_box.ResumeLayout()


class ObjectPickerForm(Form if Form is not None else object):
    def __init__(self, items, selected_index=-1, analyze_callback=None, scan_callback=None):
        self.labels = dict(PICKER_LABELS)
        self.Text = PICKER_LABELS["title"]
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
        self._analysis_queue = []
        self._analysis_cursor = 0
        self._analysis_timer = None
        self._is_closing = False
        self._sort_key = None
        self._sort_descending = False

        title = Label()
        title.Text = PICKER_LABELS["heading"]
        title.ForeColor = _TEXT
        title.Font = Font("Segoe UI", 12, FontStyle.Bold)
        title.Location = Point(16, 14)
        title.AutoSize = True
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = PICKER_LABELS["subtitle"]
        subtitle.ForeColor = _DIM
        subtitle.Location = Point(18, 45)
        subtitle.AutoSize = True
        self.Controls.Add(subtitle)

        status = Label()
        status.Text = PICKER_LABELS["status"]
        status.ForeColor = _DIM
        status.Location = Point(18, 63)
        status.AutoSize = True
        self._status = status
        status.Cursor = Cursors.Hand
        status.Click += self._show_error_report
        self.Controls.Add(status)

        search_label = Label()
        search_label.Text = "Filter:"
        search_label.ForeColor = _DIM
        search_label.Location = Point(16, 86)
        search_label.AutoSize = True
        self._search_label = search_label
        self.Controls.Add(search_label)

        search = TextBox()
        search.Location = Point(66, 82)
        search.Size = Size(320, 24)
        search.Anchor = AnchorStyles.Top | AnchorStyles.Left
        search.Text = ""
        search.TextChanged += self._on_filter_changed
        search.PreviewKeyDown += self._on_search_preview_key
        self._search = search
        self.Controls.Add(search)

        self._sort_buttons = []
        for text, key, tip in (
            ("A↑", "name", "Sort by name; click again to reverse the order"),
            ("#↑", "changes", "Sort by change count; click again to reverse the order"),
        ):
            button = Button()
            button.Text = text
            button.Size = Size(30, 24)
            button.Anchor = AnchorStyles.Top | AnchorStyles.Right
            button.Tag = key
            button.Click += self._on_sort
            self._style_button(button)
            self.Controls.Add(button)
            self._sort_buttons.append((button, tip))

        tooltip = ToolTip()
        for button, tip in self._sort_buttons:
            tooltip.SetToolTip(button, tip)
        self._sort_tooltip = tooltip

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
        cancel.Click += self._cancel
        self._style_button(cancel)
        self.Controls.Add(cancel)
        self.CancelButton = cancel
        self._cancel_button = cancel

        all_button = Button()
        all_button.Text = PICKER_LABELS["scan_button"]
        all_button.Size = Size(100, 30)
        all_button.Location = Point(750, 590)
        all_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        all_button.Click += self._accept_all
        self._style_button(all_button)
        self.Controls.Add(all_button)
        self._all_button = all_button

        selected = Button()
        selected.Text = PICKER_LABELS["open_button"]
        selected.Size = Size(120, 30)
        selected.Location = Point(860, 590)
        selected.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        selected.Click += self._accept
        self._style_button(selected)
        self.Controls.Add(selected)
        self._selected_button = selected
        self.AcceptButton = selected
        self.Resize += self._layout
        self.FormClosing += self._on_form_closing
        self.FormClosed += self._on_form_closed
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
        if status == "changed":
            color = _BEFORE
        elif status == "ok":
            color = _AFTER
        else:
            color = _TEXT if selected else _DIM
        suffix = item.get("suffix")
        if suffix is None:
            if status == "changed":
                suffix = "[{0} line(s) to fix]".format(item.get("changed_lines", 0))
            elif status == "ok":
                suffix = "[OK]"
            elif status == "error":
                suffix = "[read error]"
            elif item.get("analysis") == "running":
                suffix = "[analyzing]"
            else:
                suffix = "[not analyzed]"
        brush = SolidBrush(color)
        try:
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
        self.items[index]["analysis"] = "running"
        self.list.Invalidate()
        self._status.Text = "Analyzing selected block..."
        self.UseWaitCursor = True
        try:
            self.analyze_callback(index)
            self.list.Invalidate()
        finally:
            self.analyzing = False
            self.UseWaitCursor = False
            self._status.Text = self._analysis_status()

    def _analysis_status(self):
        # Report on the set the user is actually looking at: the queue while a
        # sweep is in flight or finished, the filtered list otherwise.
        scope = self._analysis_queue or self._visible_indexes
        total = len(scope)
        analyzed = sum(
            1 for index in scope
            if self.items[index].get("analysis") in ("done", "error")
        )
        changed = sum(1 for index in scope if self.items[index].get("status") == "changed")
        errors = sum(1 for index in scope if self.items[index].get("status") == "error")
        if total and analyzed >= total:
            return self.labels["analysis_done"].format(changed)
        suffix = ""
        if changed:
            suffix += self.labels["analysis_hits"].format(changed)
        if errors:
            suffix += " {0} could not be read (click for details).".format(errors)
        return "Analyzed {0}/{1} block(s).".format(analyzed, total) + suffix

    def _show_error_report(self, sender=None, event=None):
        lines = []
        count = 0
        for item in self.items:
            if item.get("status") == "error" or item.get("read_errors"):
                count += 1
                lines.append(item.get("label", ""))
                lines.append("    " + item.get("error", "No detail was reported."))
                lines.append("")
        if not lines:
            self._status.Text = "No read errors were reported."
            return
        header = "{0} object(s) could not be fully read:".format(count)
        show_text_report(
            self.labels["message_title"] + " - read errors",
            header + "\n\n" + "\n".join(lines),
        )

    def _start_background_analysis(self, indexes):
        if self.analyze_callback is None:
            return
        queue = pending_indexes(self.items, indexes)
        if not queue:
            self._status.Text = self._analysis_status()
            return
        self._analysis_queue = list(queue)
        self._analysis_cursor = 0
        self._stop_background_analysis()
        timer = Timer()
        timer.Interval = 15
        timer.Tick += self._on_analysis_tick
        self._analysis_timer = timer
        timer.Start()

    def _on_analysis_tick(self, sender, event):
        # A WinForms Timer is rooted by its Tick delegate and keeps ticking in
        # the host's message pump for the life of the process. FormClosed
        # normally stops it, but it does not run on every way out of a modal
        # dialog (a ScriptEngine abort unwinds ShowDialog without it). Without
        # this guard a leaked timer walks the whole project on every tick,
        # forever, inside CODESYS. Self-terminate as soon as the form is gone.
        if self._is_closing or self.IsDisposed or self.Disposing:
            self._stop_background_analysis()
            return
        if self.analyzing:
            return
        watch = Stopwatch.StartNew()
        self.analyzing = True
        try:
            while self._analysis_cursor < len(self._analysis_queue):
                index = self._analysis_queue[self._analysis_cursor]
                self._analysis_cursor += 1
                item = self.items[index]
                if item.get("analysis") is not None:
                    continue
                item["analysis"] = "running"
                self.analyze_callback(index)
                if watch.ElapsedMilliseconds >= ANALYSIS_BUDGET_MS:
                    break
        finally:
            self.analyzing = False
        if self._analysis_cursor >= len(self._analysis_queue):
            self._stop_background_analysis()
        self._status.Text = self._analysis_status()
        if self._sort_key == "changes":
            self._refresh_list()
        else:
            self.list.Invalidate()

    def _stop_background_analysis(self):
        timer = self._analysis_timer
        self._analysis_timer = None
        if timer is not None:
            timer.Stop()
            timer.Dispose()

    def _cancel(self, sender=None, event=None):
        self._is_closing = True
        self._stop_background_analysis()

    def _on_form_closing(self, sender, event):
        # FormClosed is not guaranteed when a CODESYS ScriptEngine abort
        # unwinds a modal dialog. Stop the WinForms timer before that can
        # happen, so it cannot continue walking project objects afterwards.
        self._is_closing = True
        self._stop_background_analysis()

    def _on_selection_changed(self, sender, event):
        if self.list.SelectedIndex >= 0:
            index = self._visible_indexes[self.list.SelectedIndex]
            item = self.items[index]
            if item.get("status") == "error":
                self._status.Text = "Read error: " + item.get(
                    "error", "CODESYS did not expose editable Structured Text."
                )
                return
            self._analyze_index(index)
            if item.get("status") == "error":
                self._status.Text = "Read error: " + item.get(
                    "error", "CODESYS did not expose editable Structured Text."
                )

    def _accept(self, sender, event):
        if self.list.SelectedIndex < 0:
            return
        visible = self.list.SelectedIndex
        self._analyze_index(self._visible_indexes[visible])
        self.selected_index = self._visible_indexes[visible]
        self.action = "selected"
        self._stop_background_analysis()
        self.DialogResult = DialogResult.OK
        self.Close()

    def _accept_all(self, sender=None, event=None):
        if self.scan_callback is None:
            return
        if not self._confirm_sweep(
                len(pending_indexes(self.items, self._visible_indexes))):
            return
        self._stop_background_analysis()
        self.analyzing = True
        self._status.Text = self.labels["scan_status"]
        self.UseWaitCursor = True
        try:
            try:
                index = self.scan_callback(0, self._visible_indexes, self._search.Text)
            except TypeError:
                try:
                    index = self.scan_callback(0, self._visible_indexes)
                except TypeError:
                    index = self.scan_callback(0)
            if index < 0:
                show_message(self.labels["message_title"], self.labels["scan_none"], "info")
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

    def _confirm_sweep(self, count):
        """Make the user opt in to a sweep large enough to look like a hang."""
        if count <= ANALYSIS_CONFIRM_LIMIT:
            return True
        answer = MessageBox.Show(
            "{0} block(s) still need analyzing. Each one is parsed in full, so "
            "this can take a while.\n\nNarrow the filter first, or continue?".format(count),
            self.labels["message_title"],
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question,
        )
        if answer != DialogResult.Yes:
            self._search.Focus()
            return False
        return True

    def _layout(self, sender=None, event=None):
        width = self.ClientSize.Width
        height = self.ClientSize.Height
        margin = 16
        gap = 10
        button_y = max(0, height - 42)
        self._search_label.Location = Point(margin, 86)
        search_left = margin + 50
        sort_width = sum(button.Width for button, _tip in self._sort_buttons)
        sort_width += max(0, len(self._sort_buttons) - 1) * 2
        sort_left = width - margin - sort_width
        analyze_left = sort_left
        search_width = max(150, min(320, analyze_left - 8 - search_left))
        self._search.Location = Point(search_left, 82)
        self._search.Size = Size(search_width, 24)
        for button, _tip in self._sort_buttons:
            button.Location = Point(sort_left, 82)
            sort_left = button.Right + 2
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
        selected_object = None
        if self.list.SelectedIndex >= 0 and self.list.SelectedIndex < len(self._visible_indexes):
            selected_object = self._visible_indexes[self.list.SelectedIndex]
        visible = [
            index for index, item in enumerate(self.items)
            if not query or query in item["label"].lower()
        ]
        self._visible_indexes = sort_item_indexes(
            self.items, visible, self._sort_key, self._sort_descending
        )
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

    def _on_sort(self, sender, event):
        key = sender.Tag
        if self._sort_key == key:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_key = key
            self._sort_descending = False
        for button, _tip in self._sort_buttons:
            if button.Tag == self._sort_key:
                button.Text = (
                    ("A↓" if self._sort_descending else "A↑")
                    if button.Tag == "name"
                    else ("#↓" if self._sort_descending else "#↑")
                )
            else:
                button.Text = "A↑" if button.Tag == "name" else "#↑"
        self._refresh_list()
        self.list.Invalidate()

    def _on_filter_changed(self, sender, event):
        if not hasattr(self, "list"):
            return
        self._refresh_list()
        self.list.Invalidate()

    def _on_search_preview_key(self, sender, event):
        # A single-line TextBox answers IsInputKey(Enter) with False, so
        # WinForms routes Enter as a dialog key: ProcessDialogKey reaches the
        # form and clicks AcceptButton. Claiming Enter as an input key here
        # keeps a single-line TextBox from routing it to the form's
        # AcceptButton.
        if event.KeyCode == Keys.Enter:
            event.IsInputKey = True

    def _on_form_closed(self, sender, event):
        self._stop_background_analysis()


class FmtPreviewForm(Form if Form is not None else object):
    def __init__(self, object_name, before, after, changed_lines, wizard_mode=False,
                 wizard_callback=None):
        self.Text = "FMT Preview - " + (object_name or "Structured Text")
        self.Size = Size(1600, 980)
        self.MinimumSize = Size(1050, 650)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.AutoScaleMode = AutoScaleMode.Font
        self.BackColor = _BG
        self.action = "stop"
        self.wizard_mode = wizard_mode
        self._wizard_callback = wizard_callback

        title = Label()
        title.Text = object_name or "Structured Text"
        title.ForeColor = _TEXT
        title.Font = Font("Segoe UI", 12, FontStyle.Bold)
        title.Location = Point(16, 12)
        title.AutoSize = True
        self.Controls.Add(title)
        self._title_label = title

        stats = Label()
        stats.Text = self._stats_text(changed_lines)
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
        self._stats_label = stats
        self._changed_left = set()
        self._changed_right = set()
        self._jump_index = -1
        self._view_style = (
            (_FMT_PREVIEW_STATE or {}).get("view_style", "side_by_side")
        )

        self._before = self._text_box(before or "")
        self._after = self._text_box(after or "")
        self._line_by_line = self._text_box("")
        self._before.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self._after.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self._line_by_line.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(self._before)
        self.Controls.Add(self._after)
        self.Controls.Add(self._line_by_line)
        self._before.VScroll += self._sync_scroll
        self._after.VScroll += self._sync_scroll
        self._before.HScroll += self._sync_scroll
        self._after.HScroll += self._sync_scroll
        self.Resize += self._on_resize

        stop = Button()
        stop.Text = "Stop" if wizard_mode else "Cancel"
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
        skip.Visible = wizard_mode
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
        previous.Enabled = bool(changed_lines)
        self.Controls.Add(previous)
        self._previous_button = previous
        next_button = Button()
        next_button.Text = "Next change"
        next_button.Size = Size(105, 32)
        next_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        next_button.Click += self._next_change
        self._style_button(next_button)
        next_button.Enabled = bool(changed_lines)
        self.Controls.Add(next_button)
        self._next_button = next_button
        view_label = Label()
        view_label.Text = "View:"
        view_label.ForeColor = _DIM
        view_label.AutoSize = True
        self.Controls.Add(view_label)
        self._view_label = view_label
        side_by_side = Button()
        side_by_side.Text = "Two panes"
        side_by_side.Size = Size(95, 26)
        side_by_side.Anchor = AnchorStyles.Top | AnchorStyles.Right
        side_by_side.Click += self._show_side_by_side
        self._style_button(side_by_side)
        self.Controls.Add(side_by_side)
        self._side_by_side_button = side_by_side
        line_by_line = Button()
        line_by_line.Text = "By line"
        line_by_line.Size = Size(80, 26)
        line_by_line.Anchor = AnchorStyles.Top | AnchorStyles.Right
        line_by_line.Click += self._show_line_by_line
        self._style_button(line_by_line)
        self.Controls.Add(line_by_line)
        self._line_by_line_button = line_by_line
        tooltip = ToolTip()
        tooltip.SetToolTip(previous, "Jump to the previous changed line in this block")
        tooltip.SetToolTip(next_button, "Jump to the next changed line in this block")
        tooltip.SetToolTip(side_by_side, "Show Before and After in two synchronized panes")
        tooltip.SetToolTip(line_by_line, "Show unchanged lines once and each change as Before/After rows")
        self._tooltip = tooltip
        self._set_line_by_line_text(before, after)
        self._set_view_style(self._view_style)
        self._layout()
        self._highlight(before, after)
        self._restore_preview_state()

    def load_preview(self, object_name, before, after, changed_lines):
        """Replace the current wizard page without closing the form."""
        self.Text = "FMT Preview - " + (object_name or "Structured Text")
        self._title_label.Text = object_name or "Structured Text"
        self._stats_label.Text = self._stats_text(changed_lines)
        self._before.Text = before or ""
        self._after.Text = after or ""
        self._set_line_by_line_text(before, after)
        self._jump_index = -1
        self._highlight(before, after)
        self._previous_button.Enabled = bool(changed_lines)
        self._next_button.Enabled = bool(changed_lines)

    def _advance_wizard(self, action):
        if self._wizard_callback is None:
            return False
        outcome = self._wizard_callback(action) or {}
        if outcome.get("next"):
            preview = outcome["next"]
            self.load_preview(
                preview["object_name"], preview["before"], preview["after"],
                preview["changed_lines"],
            )
        elif outcome.get("complete"):
            self.action = "complete"
            self.DialogResult = DialogResult.OK
            self.Close()
        # Errors are reported by the operation and leave this page open.
        return True

    def _restore_preview_state(self):
        state = _FMT_PREVIEW_STATE
        if not state:
            return
        self.StartPosition = FormStartPosition.Manual
        self.Location = state["location"]
        self.Size = state["size"]
        self.WindowState = state["window_state"]

    def remember_preview_state(self):
        global _FMT_PREVIEW_STATE
        bounds = self.RestoreBounds
        _FMT_PREVIEW_STATE = {
            "location": bounds.Location,
            "size": bounds.Size,
            "window_state": self.WindowState,
            "view_style": self._view_style,
        }

    def _stats_text(self, changed_lines):
        if self.wizard_mode:
            return (
                "FMT preview - {0} changed line(s). Changes are applied directly "
                "to the IDE; use Undo if needed. Apply, skip, or stop."
            ).format(changed_lines)
        return (
            "FMT preview - {0} changed line(s). Changed characters are highlighted. "
            "Previous/Next change jumps between modified lines. Apply or cancel."
        ).format(changed_lines)

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
        _highlight_changed_characters(
            self._before, self._after, before, after, sorted(left)
        )

    def _set_line_by_line_text(self, before, after):
        text, removed, added = _line_by_line_diff(before, after)
        self._line_by_line.Text = text
        self._inline_change_rows = sorted(removed)
        _highlight_lines(self._line_by_line, removed, _CHANGED_BG)
        _highlight_lines(self._line_by_line, added, _ADDED_BG)

    def _set_view_style(self, style):
        self._view_style = "line_by_line" if style == "line_by_line" else "side_by_side"
        inline = self._view_style == "line_by_line"
        self._before.Visible = not inline
        self._after.Visible = not inline
        self._line_by_line.Visible = inline
        self._after_label.Visible = not inline
        self._side_by_side_button.Enabled = inline
        self._line_by_line_button.Enabled = not inline
        self._layout()

    def _show_side_by_side(self, sender, event):
        self._set_view_style("side_by_side")

    def _show_line_by_line(self, sender, event):
        self._set_view_style("line_by_line")

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
        self._line_by_line.Location = Point(left, 100)
        self._line_by_line.Size = Size(width - left * 2, box_height)
        self._after_label.Location = Point(left + half + gap, 76)
        self._line_by_line_button.Location = Point(width - left - self._line_by_line_button.Width, 70)
        self._side_by_side_button.Location = Point(
            self._line_by_line_button.Left - 6 - self._side_by_side_button.Width, 70
        )
        self._view_label.Location = Point(self._side_by_side_button.Left - 42, 76)
        button_y = max(0, height - 48)
        self._stop_button.Location = Point(width - 16 - self._stop_button.Width, button_y)
        self._skip_button.Location = Point(
            self._stop_button.Left - 10 - self._skip_button.Width, button_y
        )
        if self.wizard_mode:
            self._apply_button.Location = Point(
                self._skip_button.Left - 10 - self._apply_button.Width, button_y
            )
        else:
            self._apply_button.Location = Point(
                self._stop_button.Left - 10 - self._apply_button.Width, button_y
            )
        self._previous_button.Location = Point(left, button_y)
        self._next_button.Location = Point(
            self._previous_button.Right + 8, button_y
        )

    def _on_resize(self, sender, event):
        self._layout()

    def _apply(self, sender, event):
        if self._advance_wizard("apply"):
            return
        self.action = "apply"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _skip(self, sender, event):
        if self._advance_wizard("skip"):
            return
        self.action = "skip"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _sync_scroll(self, sender, event):
        other = self._after if sender is self._before else self._before
        if getattr(self, "_syncing_scroll", False):
            return
        self._syncing_scroll = True
        try:
            # SelectionStart is not the viewport position.  Using it makes a
            # scrollbar event move the other pane to an unrelated line,
            # especially after jumping to a change.  The character at the
            # top-left client point is the first visible line in both panes;
            # the formatter preserves line count, so the line can be shared.
            top_left = sender.GetCharIndexFromPosition(Point(2, 2))
            line = sender.GetLineFromCharIndex(top_left)
            if line < 0 or line >= other.Lines.Length:
                return
            target = other.GetFirstCharIndexFromLine(line)
            if target < 0:
                return
            other.Select(target, 0)
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
        self._stats_label.Text = self._stats_text_with_position(target)
        if self._view_style == "line_by_line":
            position = self._changed_left.index(target)
            if position < len(self._inline_change_rows):
                row = self._inline_change_rows[position]
                start = self._line_by_line.GetFirstCharIndexFromLine(row)
                self._line_by_line.Select(max(0, start), len(self._line_by_line.Lines[row]))
                self._line_by_line.ScrollToCaret()
            return
        for box in (self._before, self._after):
            if target < box.Lines.Length:
                start = box.GetFirstCharIndexFromLine(target)
                box.Select(max(0, start), len(box.Lines[target]))
                box.ScrollToCaret()

    def _stats_text_with_position(self, target):
        position = self._changed_left.index(target) + 1
        total = len(self._changed_left)
        return "Change {0} of {1}. Previous/Next change jumps between modified lines.".format(
            position, total
        )

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
    try:
        form.ShowDialog()
        return form.action, form.selected_index
    finally:
        # Be defensive: CODESYS can unwind ShowDialog without delivering the
        # normal close events. A live Timer delegate would otherwise retain
        # the form and continue scanning in the Scripting Engine.
        form._is_closing = True
        form._stop_background_analysis()
        form.Dispose()


def show_fmt_preview(object_name, before, after, changed_lines, wizard_mode=False):
    if Form is None:
        return "stop"
    form = FmtPreviewForm(
        object_name, before, after, changed_lines, wizard_mode=wizard_mode
    )
    form.ShowDialog()
    form.remember_preview_state()
    return form.action


def show_fmt_wizard(first_preview, advance_callback):
    """Review several formatter changes in one persistent preview window."""
    if Form is None:
        return "stop"
    form = FmtPreviewForm(
        first_preview["object_name"],
        first_preview["before"],
        first_preview["after"],
        first_preview["changed_lines"],
        wizard_mode=True,
        wizard_callback=advance_callback,
    )
    form.ShowDialog()
    form.remember_preview_state()
    return form.action


def show_text_report(title, text):
    if Form is None:
        print("[FMT] " + str(text))
        return
    form = Form()
    form.Text = title
    form.Size = Size(900, 600)
    form.MinimumSize = Size(500, 300)
    form.StartPosition = FormStartPosition.CenterScreen
    form.FormBorderStyle = FormBorderStyle.Sizable
    form.BackColor = _BG

    box = RichTextBox()
    box.ReadOnly = True
    box.WordWrap = False
    box.ScrollBars = RichTextBoxScrollBars.Both
    box.BackColor = _PANEL
    box.ForeColor = _TEXT
    box.BorderStyle = getattr(BorderStyle, "None")
    box.Font = Font("Consolas", 9)
    box.Location = Point(12, 12)
    box.Size = Size(864, 500)
    box.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
    box.Text = text
    form.Controls.Add(box)

    close = Button()
    close.Text = "Close"
    close.Size = Size(90, 30)
    close.Location = Point(770, 524)
    close.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
    close.DialogResult = DialogResult.Cancel
    close.BackColor = _BUTTON_BG
    close.ForeColor = _TEXT
    close.FlatStyle = FlatStyle.Flat
    close.FlatAppearance.BorderColor = _BUTTON_BORDER
    close.FlatAppearance.BorderSize = 1
    close.UseVisualStyleBackColor = False
    form.Controls.Add(close)
    form.CancelButton = close

    try:
        form.ShowDialog()
    finally:
        form.Dispose()


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

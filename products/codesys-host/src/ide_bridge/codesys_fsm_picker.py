# -*- coding: utf-8 -*-
"""WinForms object picker for the CODESYS ``fsm`` command.

This module is IronPython 2.7 safe (no f-strings, no annotations, no
dataclasses) and must import cleanly under CPython with ``Form = None``.
"""
from __future__ import print_function

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, Label, Button, ListBox, RichTextBox, TextBox, MessageBox,
        MessageBoxButtons, MessageBoxIcon, DialogResult, FormBorderStyle,
        FormStartPosition, AnchorStyles, BorderStyle, RichTextBoxScrollBars,
        FlatStyle, DrawMode, DrawItemState, AutoScaleMode, Application, ToolTip,
        Keys, Cursors, TextRenderer
    )
    from System.Drawing import Size, Point, Font, FontStyle, Color, SolidBrush
except Exception:
    Form = None
    Application = None

from ide_picker_common import pending_indexes, sort_item_indexes


# Copy strings for the FSM object picker. Plain strings, defined outside the
# CLR guard so they exist even when WinForms is unavailable. The FSM command
# always runs with deferred analysis, a required search, and external search,
# so those three flags are folded into the picker's behaviour rather than kept
# as data here.
FSM_PICKER_LABELS = {
    "title": "FSM - Select object",
    "heading": "Find a state machine in the exported workspace",
    "subtitle": "Enter a path search and press Enter to list matching project-view blocks. Then Find next FSM analyzes them one at a time, stopping at each state machine.",
    "status": "Enter a search term and press Enter first.",
    "scan_button": "Find next FSM",
    "stop_button": "Stop",
    "open_button": "Show diagram",
    "analyze_button": "Analyze filtered",
    "scan_status": "Searching matching workspace files...",
    "scan_none": "No state machine was found in the matching blocks.",
    "scan_hit": "State machine found in '{0}'. Find next FSM continues from the next block.",
    "scan_stopped": "Scan stopped. Find next FSM resumes from where it stopped.",
    "analysis_done": "Analysis complete - {0} block(s) contain a state machine.",
    "analysis_hits": " {0} contain a state machine.",
    "message_title": "FSM",
    "search_prompt": "Enter a non-empty path search and press Enter first.",
}


if Form is not None:
    _BG = Color.FromArgb(30, 30, 30)
    _PANEL = Color.FromArgb(37, 37, 38)
    _TEXT = Color.FromArgb(225, 225, 225)
    _DIM = Color.FromArgb(160, 160, 160)
    _BUTTON_BG = Color.FromArgb(72, 72, 78)
    _BUTTON_BORDER = Color.FromArgb(115, 115, 125)
    _BEFORE = Color.FromArgb(245, 180, 100)
    _AFTER = Color.FromArgb(125, 220, 145)


class FsmObjectPickerForm(Form if Form is not None else object):
    def __init__(self, items, selected_index=-1, analyze_callback=None, scan_callback=None,
                 snapshot_notice=None, view_callback=None):
        self.labels = dict(FSM_PICKER_LABELS)
        self.Text = FSM_PICKER_LABELS["title"]
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
        # With a view callback the diagram opens on top of this window and the
        # picker survives it, so one sitting can walk through many machines.
        self.view_callback = view_callback
        self.viewed_count = 0
        self._search_confirmed = False
        self.analyzing = False
        self._is_closing = False
        self._scanning = False
        self._stop_requested = False
        self._status = None
        self._listed_query = None
        self._snapshot_notice = snapshot_notice
        self._visible_indexes = list(range(len(items)))
        self._analysis_queue = []
        self._analysis_cursor = 0
        self._sort_key = None
        self._sort_descending = False
        # Deferred mode parses nothing until the user presses Analyze. On a
        # large project the up-front sweep is what made this dialog unusable.
        self._deferred = True

        title = Label()
        title.Text = FSM_PICKER_LABELS["heading"]
        title.ForeColor = _TEXT
        title.Font = Font("Segoe UI", 12, FontStyle.Bold)
        title.Location = Point(16, 14)
        title.AutoSize = True
        self.Controls.Add(title)

        subtitle = Label()
        subtitle.Text = FSM_PICKER_LABELS["subtitle"]
        subtitle.ForeColor = _DIM
        subtitle.Location = Point(18, 45)
        subtitle.AutoSize = True
        self.Controls.Add(subtitle)

        snapshot = Label()
        snapshot.Text = snapshot_notice or ""
        snapshot.ForeColor = _BEFORE
        snapshot.Location = Point(18, 63)
        snapshot.AutoSize = True
        self._snapshot_label = snapshot
        self.Controls.Add(snapshot)

        status = Label()
        status.Text = FSM_PICKER_LABELS["status"]
        status.ForeColor = _DIM
        status.Location = Point(18, 80)
        status.AutoSize = True
        self._status = status
        status.Cursor = Cursors.Hand
        status.Click += self._show_error_report
        self.Controls.Add(status)

        search_label = Label()
        search_label.Text = "Path search:"
        search_label.ForeColor = _DIM
        search_label.Location = Point(16, 103)
        search_label.AutoSize = True
        self._search_label = search_label
        self.Controls.Add(search_label)

        search = TextBox()
        search.Location = Point(66, 99)
        search.Size = Size(320, 24)
        search.Anchor = AnchorStyles.Top | AnchorStyles.Left
        search.Text = ""
        search.TextChanged += self._on_filter_changed
        search.PreviewKeyDown += self._on_search_preview_key
        search.KeyDown += self._on_search_key_down
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
        self.list.Location = Point(16, 131)
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
        all_button.Text = FSM_PICKER_LABELS["scan_button"]
        all_button.Size = Size(100, 30)
        all_button.Location = Point(750, 590)
        all_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        all_button.Click += self._accept_all
        self._style_button(all_button)
        self.Controls.Add(all_button)
        self._all_button = all_button

        selected = Button()
        selected.Text = FSM_PICKER_LABELS["open_button"]
        selected.Size = Size(120, 30)
        selected.Location = Point(860, 590)
        selected.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        selected.Click += self._accept
        self._style_button(selected)
        self.Controls.Add(selected)
        self._selected_button = selected
        self.AcceptButton = selected
        self.Resize += self._layout
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
        except Exception as error:
            item = self.items[index]
            item["analysis"] = "error"
            item["status"] = "error"
            item["suffix"] = "[read error]"
            item["error"] = str(error)
            self._status.Text = "FSM search failed: " + str(error)
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
            return FSM_PICKER_LABELS["analysis_done"].format(changed)
        suffix = ""
        if changed:
            suffix += FSM_PICKER_LABELS["analysis_hits"].format(changed)
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
            FSM_PICKER_LABELS["message_title"] + " - read errors",
            header + "\n\n" + "\n".join(lines),
        )

    def _start_background_analysis(self, indexes):
        """Sweep the listed blocks, stopping at the first state machine.

        Driven straight from the click and paced by DoEvents rather than by a
        WinForms timer: WM_TIMER is the lowest-priority message there is, and
        inside the IDE's nested modal pump a queued tick could sit unserved -
        the click retitled the button and then nothing ever happened.
        """
        if self.analyze_callback is None or self._scanning:
            return
        queue = pending_indexes(self.items, indexes)
        if not queue:
            self._status.Text = self._analysis_status()
            return
        self._analysis_queue = list(queue)
        self._analysis_cursor = 0
        self._run_scan()

    def _run_scan(self):
        """Walk the queue from the cursor to the next hit, stop or exhaustion."""
        self._scanning = True
        self._stop_requested = False
        self.analyzing = True
        self._set_scan_button_text(FSM_PICKER_LABELS["stop_button"])
        hit = -1
        try:
            while self._analysis_cursor < len(self._analysis_queue):
                if self._stop_requested or self._closed_or_closing():
                    break
                index = self._analysis_queue[self._analysis_cursor]
                self._analysis_cursor += 1
                if self.items[index].get("analysis") is not None:
                    continue
                self._analyze_queued(index)
                self._report_progress(index)
                if self.items[index].get("status") == "changed":
                    hit = index
                    break
        finally:
            self._scanning = False
            self.analyzing = False
            self._set_scan_button_text(FSM_PICKER_LABELS["scan_button"])
        if self._closed_or_closing():
            return
        if hit >= 0:
            self._open_scan_hit(hit)
            return
        if self._analysis_cursor >= len(self._analysis_queue):
            self._status.Text = FSM_PICKER_LABELS["scan_none"]
        else:
            self._status.Text = FSM_PICKER_LABELS["scan_stopped"]
        self._refresh_after_scan()

    def _closed_or_closing(self):
        return bool(
            getattr(self, "_is_closing", False) or self.IsDisposed or self.Disposing
        )

    def _analyze_queued(self, index):
        item = self.items[index]
        item["analysis"] = "running"
        try:
            self.analyze_callback(index)
        except Exception as error:
            item["analysis"] = "error"
            item["status"] = "error"
            item["suffix"] = "[read error]"
            item["error"] = str(error)

    def _report_progress(self, index):
        self._status.Text = "Analyzing {0}/{1}: {2}".format(
            self._analysis_cursor, len(self._analysis_queue), self.items[index]["label"]
        )
        self._pump()

    def _pump(self):
        """Repaint and let the click that stops the sweep through."""
        if Application is None:
            return
        try:
            self._status.Refresh()
            self.list.Invalidate()
            Application.DoEvents()
        except Exception:
            pass

    def _refresh_after_scan(self):
        if self._sort_key == "changes":
            self._refresh_list()
        else:
            self.list.Invalidate()

    def _set_scan_button_text(self, text):
        """The scan button doubles as Stop, so it is retitled while a scan runs."""
        button = getattr(self, "_all_button", None)
        if button is None or self.IsDisposed or self.Disposing:
            return
        button.Text = text

    def _stop_background_analysis(self):
        """Ask a running sweep to stop; safe to call when none is running."""
        self._stop_requested = True

    def _on_selection_changed(self, sender, event):
        if not self._search_confirmed:
            return
        if self._deferred:
            return

    def _accept(self, sender, event):
        if self._scanning:
            # Reached through DoEvents from inside the sweep. Opening a diagram
            # on top of a running sweep would nest the two.
            self._status.Text = "A scan is running - press Stop first."
            return
        if not self._search_confirmed:
            if (self.list.SelectedIndex < 0
                    and (self._search.Text or "").strip()):
                self._search_confirmed = True
                self._status.Text = FSM_PICKER_LABELS["scan_status"]
                self._accept_all()
                return
            self._status.Text = FSM_PICKER_LABELS["search_prompt"]
            self._search.Focus()
            return
        if self.list.SelectedIndex < 0:
            return
        visible = self.list.SelectedIndex
        index = self._visible_indexes[visible]
        self._analyze_index(index)
        item = self.items[index]
        if item.get("status") in ("error", "ok"):
            self._status.Text = item.get("error") or "No state machine was found in '{0}'.".format(item["label"])
            self.list.Invalidate()
            return
        self.selected_index = index
        if self.view_callback is not None:
            self._show_diagram(index)
            return
        self.action = "selected"
        self.DialogResult = DialogResult.OK
        self.Close()

    def _accept_all(self, sender=None, event=None):
        if self.scan_callback is None:
            return
        if not self._search_confirmed:
            self._status.Text = FSM_PICKER_LABELS["search_prompt"]
            self._search.Focus()
            return
        current_query = (self._search.Text or "").strip()
        if current_query == self._listed_query:
            if self._scanning:
                # Re-entered through DoEvents from inside the sweep: the sweep
                # itself checks this flag between blocks.
                self._stop_requested = True
                return
            self._start_background_analysis(self._visible_indexes)
            return
        self._stop_background_analysis()
        self.analyzing = True
        self._status.Text = FSM_PICKER_LABELS["scan_status"]
        self.UseWaitCursor = True
        try:
            index = self.scan_callback(0, self._visible_indexes, self._search.Text)
            if isinstance(index, dict):
                self._listed_query = (self._search.Text or "").strip()
                self._analysis_queue = []
                self._analysis_cursor = 0
                self._refresh_list()
                self._status.Text = index.get("status", "Search complete.")
                return
            if index < 0:
                show_message(FSM_PICKER_LABELS["message_title"], FSM_PICKER_LABELS["scan_none"], "info")
                self.list.Invalidate()
                return
            self._open_scan_hit(index)
        except Exception as error:
            self._status.Text = "FSM search failed: " + str(error)
        finally:
            self.analyzing = False
            self.UseWaitCursor = False

    def _open_scan_hit(self, index):
        """Select the block the scan settled on and show it, without closing."""
        self.selected_index = index
        if index in self._visible_indexes:
            self.list.SelectedIndex = self._visible_indexes.index(index)
        self._refresh_after_scan()
        if self.view_callback is None:
            self.action = "all"
            self.DialogResult = DialogResult.OK
            self.Close()
            return
        self._status.Text = FSM_PICKER_LABELS["scan_hit"].format(self.items[index]["label"])
        self._show_diagram(index)

    def _show_diagram(self, index):
        """Open the diagram on top of this window and come back to it."""
        if self.view_callback is None:
            return False
        item = self.items[index]
        try:
            shown = self.view_callback(index)
        except Exception as error:
            self._status.Text = "FSM diagram failed: " + str(error)
            return False
        if not shown:
            self._status.Text = item.get("error") or "No state machine was found in '{0}'.".format(item["label"])
            self.list.Invalidate()
            return False
        self.viewed_count += 1
        self._status.Text = FSM_PICKER_LABELS["scan_hit"].format(item["label"])
        self.list.Invalidate()
        return True

    def _layout(self, sender=None, event=None):
        width = self.ClientSize.Width
        height = self.ClientSize.Height
        margin = 16
        gap = 10
        button_y = max(0, height - 42)
        self._search_label.Location = Point(margin, 103)
        label_width = TextRenderer.MeasureText(
            self._search_label.Text, self._search_label.Font
        ).Width
        search_left = margin + label_width + 8
        sort_width = sum(button.Width for button, _tip in self._sort_buttons)
        sort_width += max(0, len(self._sort_buttons) - 1) * 2
        sort_left = width - margin - sort_width
        analyze_left = sort_left
        search_width = max(150, min(320, analyze_left - 8 - search_left))
        self._search.Location = Point(search_left, 99)
        self._search.Size = Size(search_width, 24)
        for button, _tip in self._sort_buttons:
            button.Location = Point(sort_left, 99)
            sort_left = button.Right + 2
        self.list.Location = Point(margin, 131)
        self.list.Size = Size(max(100, width - margin * 2), max(100, button_y - 141))
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
        # The queue was built from the previous filter. Per-item results
        # are cached, so nothing is lost by dropping the stale sweep.
        self._stop_background_analysis()
        self._search_confirmed = False
        self._refresh_list()
        self.list.Invalidate()

    def _on_search_preview_key(self, sender, event):
        if event.KeyCode == Keys.Enter:
            event.IsInputKey = True

    def _on_search_key_down(self, sender, event):
        if event.KeyCode != Keys.Enter:
            return
        event.Handled = True
        event.SuppressKeyPress = True
        if not (self._search.Text or "").strip():
            self._status.Text = FSM_PICKER_LABELS["search_prompt"]
            return
        self._search_confirmed = True
        self._status.Text = "Searching matching workspace files..."
        self._accept_all()

    def _on_form_closed(self, sender, event):
        self._is_closing = True
        self._stop_background_analysis()


def show_fsm_object_picker(items, selected_index=-1, analyze_callback=None, scan_callback=None,
                           snapshot_notice=None, view_callback=None):
    if Form is None:
        return "cancel", -1
    form = FsmObjectPickerForm(
        items,
        selected_index=selected_index,
        analyze_callback=analyze_callback,
        scan_callback=scan_callback,
        snapshot_notice=snapshot_notice,
        view_callback=view_callback,
    )
    form.ShowDialog()
    return form.action, form.selected_index


def show_text_report(title, text):
    if Form is None:
        print("[FSM] " + str(text))
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
        print("[FSM] " + str(message))
        return
    message_icon = MessageBoxIcon.Information
    if icon == "warning":
        message_icon = MessageBoxIcon.Warning
    elif icon == "error":
        message_icon = MessageBoxIcon.Error
    MessageBox.Show(message, title, MessageBoxButtons.OK, message_icon)

# -*- coding: utf-8 -*-
"""
codesys_ui_diff.py - Side-by-side diff viewer for compare UI.
"""
from __future__ import print_function

import difflib

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, Panel, RichTextBox, Label, Button, RichTextBoxScrollBars,
        FormBorderStyle, FormStartPosition, DialogResult, DockStyle,
        AnchorStyles, BorderStyle, Padding, MessageBox, MessageBoxButtons,
        MessageBoxIcon, FlatStyle
    )
    from System.Drawing import Size, Point, Font, FontStyle, Color
except Exception:
    Form = None


def compute_side_by_side_diff(left_text, right_text):
    left_lines = (left_text or "").splitlines()
    right_lines = (right_text or "").splitlines()
    result = []
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                result.append((left_lines[i], right_lines[j], "equal"))
        elif tag == "replace":
            max_len = max(i2 - i1, j2 - j1)
            for offset in range(max_len):
                has_left = offset < (i2 - i1)
                has_right = offset < (j2 - j1)
                if has_left and has_right:
                    result.append((left_lines[i1 + offset], right_lines[j1 + offset], "modified"))
                elif has_left:
                    result.append((left_lines[i1 + offset], "", "removed"))
                else:
                    result.append(("", right_lines[j1 + offset], "added"))
        elif tag == "delete":
            for i in range(i1, i2):
                result.append((left_lines[i], "", "removed"))
        elif tag == "insert":
            for j in range(j1, j2):
                result.append(("", right_lines[j], "added"))

    return result


if Form is not None:
    CLR_BG = Color.FromArgb(30, 30, 30)
    CLR_PANEL = Color.FromArgb(37, 37, 38)
    CLR_TEXT = Color.FromArgb(220, 220, 220)
    CLR_DIM = Color.FromArgb(120, 120, 120)
    CLR_HEADER = Color.FromArgb(45, 45, 48)
    CLR_BUTTON_BG = Color.FromArgb(72, 72, 78)
    CLR_BUTTON_BORDER = Color.FromArgb(115, 115, 125)
    CLR_BUTTON_TEXT = Color.FromArgb(245, 245, 245)
    CLR_ADDED_BG = Color.FromArgb(35, 65, 35)
    CLR_ADDED = Color.FromArgb(130, 230, 130)
    CLR_REMOVED_BG = Color.FromArgb(75, 30, 30)
    CLR_REMOVED = Color.FromArgb(245, 130, 130)
    CLR_MOD_LEFT_BG = Color.FromArgb(75, 55, 20)
    CLR_MOD_LEFT = Color.FromArgb(245, 205, 110)
    CLR_MOD_RIGHT_BG = Color.FromArgb(30, 55, 75)
    CLR_MOD_RIGHT = Color.FromArgb(120, 205, 245)


class DiffViewerForm(Form if Form is not None else object):
    def __init__(self, left_text, right_text, left_title, right_title, object_name):
        self.Text = "Diff: " + (object_name or "object")
        self.Size = Size(1120, 720)
        self.MinimumSize = Size(700, 440)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor = CLR_BG
        self._left_text = left_text or ""
        self._right_text = right_text or ""
        self._change_positions = []
        self._current_change = -1

        top = Panel()
        top.Dock = DockStyle.Top
        top.Height = 62
        top.BackColor = CLR_HEADER
        self.Controls.Add(top)

        title = Label()
        title.Text = object_name or "Object diff"
        title.ForeColor = CLR_TEXT
        title.Font = Font("Segoe UI", 11, FontStyle.Bold)
        title.AutoSize = True
        title.Location = Point(12, 8)
        top.Controls.Add(title)

        self._stats = Label()
        self._stats.ForeColor = CLR_DIM
        self._stats.AutoSize = True
        self._stats.Location = Point(820, 10)
        self._stats.Anchor = AnchorStyles.Top | AnchorStyles.Right
        top.Controls.Add(self._stats)

        left_label = Label()
        left_label.Text = left_title
        left_label.ForeColor = CLR_ADDED
        left_label.AutoSize = True
        left_label.Location = Point(15, 39)
        top.Controls.Add(left_label)

        self._right_label = Label()
        self._right_label.Text = right_title
        self._right_label.ForeColor = CLR_MOD_RIGHT
        self._right_label.AutoSize = True
        self._right_label.Location = Point(570, 39)
        top.Controls.Add(self._right_label)

        bottom = Panel()
        bottom.Dock = DockStyle.Bottom
        bottom.Height = 45
        bottom.BackColor = CLR_HEADER
        self.Controls.Add(bottom)

        close_btn = Button()
        close_btn.Text = "Close"
        close_btn.Size = Size(90, 28)
        close_btn.Location = Point(10, 8)
        close_btn.DialogResult = DialogResult.Cancel
        self._style_button(close_btn)
        bottom.Controls.Add(close_btn)
        self.CancelButton = close_btn

        prev_btn = Button()
        prev_btn.Text = "<< Prev"
        prev_btn.Size = Size(80, 28)
        prev_btn.Location = Point(118, 8)
        prev_btn.Click += self._on_prev
        self._style_button(prev_btn)
        bottom.Controls.Add(prev_btn)

        next_btn = Button()
        next_btn.Text = "Next >>"
        next_btn.Size = Size(80, 28)
        next_btn.Location = Point(204, 8)
        next_btn.Click += self._on_next
        self._style_button(next_btn)
        bottom.Controls.Add(next_btn)

        self._nav = Label()
        self._nav.ForeColor = CLR_DIM
        self._nav.AutoSize = True
        self._nav.Location = Point(300, 14)
        bottom.Controls.Add(self._nav)

        content = Panel()
        content.Dock = DockStyle.Fill
        content.Padding = Padding(6, 6, 6, 6)
        content.BackColor = CLR_BG
        self.Controls.Add(content)
        content.BringToFront()

        self._left_box = self._create_text_box()
        self._right_box = self._create_text_box()
        self._separator = Panel()
        self._separator.BackColor = Color.FromArgb(70, 70, 70)
        self._separator.Width = 2

        content.Controls.Add(self._right_box)
        content.Controls.Add(self._separator)
        content.Controls.Add(self._left_box)
        self._content = content
        self.Resize += self._on_resize

        self._populate()
        self._layout()

    def _style_button(self, button):
        button.BackColor = CLR_BUTTON_BG
        button.ForeColor = CLR_BUTTON_TEXT
        button.FlatStyle = FlatStyle.Flat
        button.FlatAppearance.BorderColor = CLR_BUTTON_BORDER
        button.FlatAppearance.BorderSize = 1
        button.UseVisualStyleBackColor = False

    def _create_text_box(self):
        box = RichTextBox()
        box.ReadOnly = True
        box.BackColor = CLR_PANEL
        box.ForeColor = CLR_TEXT
        box.Font = Font("Consolas", 10)
        box.BorderStyle = getattr(BorderStyle, "None")
        box.WordWrap = False
        box.ScrollBars = RichTextBoxScrollBars.Both
        box.DetectUrls = False
        return box

    def _layout(self):
        width = self._content.ClientSize.Width
        height = self._content.ClientSize.Height
        half = (width - 2) // 2
        self._left_box.Location = Point(0, 0)
        self._left_box.Size = Size(half, height)
        self._separator.Location = Point(half, 0)
        self._separator.Size = Size(2, height)
        self._right_box.Location = Point(half + 2, 0)
        self._right_box.Size = Size(width - half - 2, height)
        self._right_label.Location = Point(max(570, self.ClientSize.Width // 2 + 12), 39)

    def _on_resize(self, sender, event):
        self._layout()

    def _append_line(self, box, prefix, prefix_color, text, text_color, bg_color):
        start = box.TextLength
        box.AppendText(prefix)
        box.Select(start, len(prefix))
        box.SelectionColor = prefix_color
        if bg_color is not None:
            box.SelectionBackColor = bg_color
        text_start = box.TextLength
        box.AppendText(text + "\n")
        box.Select(text_start, len(text))
        box.SelectionColor = text_color
        if bg_color is not None:
            box.SelectionBackColor = bg_color

    def _populate(self):
        diff_lines = compute_side_by_side_diff(self._left_text, self._right_text)
        added = sum(1 for _, _, status in diff_lines if status == "added")
        removed = sum(1 for _, _, status in diff_lines if status == "removed")
        modified = sum(1 for _, _, status in diff_lines if status == "modified")
        equal = sum(1 for _, _, status in diff_lines if status == "equal")
        self._stats.Text = "+{0} -{1} ~{2} ={3} lines".format(added, removed, modified, equal)

        left_line = 0
        right_line = 0
        in_change = False
        for left, right, status in diff_lines:
            if status == "equal":
                left_line += 1
                right_line += 1
                self._append_line(self._left_box, "{0:>5}  ".format(left_line), CLR_DIM, left, CLR_TEXT, None)
                self._append_line(self._right_box, "{0:>5}  ".format(right_line), CLR_DIM, right, CLR_TEXT, None)
                in_change = False
            elif status == "removed":
                if not in_change:
                    self._change_positions.append(self._left_box.TextLength)
                    in_change = True
                left_line += 1
                self._append_line(self._left_box, "{0:>5} -".format(left_line), CLR_REMOVED, left, CLR_REMOVED, CLR_REMOVED_BG)
                self._append_line(self._right_box, "       ", CLR_DIM, "", CLR_TEXT, None)
            elif status == "added":
                if not in_change:
                    self._change_positions.append(self._left_box.TextLength)
                    in_change = True
                right_line += 1
                self._append_line(self._left_box, "       ", CLR_DIM, "", CLR_TEXT, None)
                self._append_line(self._right_box, "{0:>5} +".format(right_line), CLR_ADDED, right, CLR_ADDED, CLR_ADDED_BG)
            else:
                if not in_change:
                    self._change_positions.append(self._left_box.TextLength)
                    in_change = True
                left_line += 1
                right_line += 1
                self._append_line(self._left_box, "{0:>5} ~".format(left_line), CLR_MOD_LEFT, left, CLR_MOD_LEFT, CLR_MOD_LEFT_BG)
                self._append_line(self._right_box, "{0:>5} ~".format(right_line), CLR_MOD_RIGHT, right, CLR_MOD_RIGHT, CLR_MOD_RIGHT_BG)

        self._nav.Text = "{0} changes".format(len(self._change_positions))
        self._left_box.SelectionStart = 0
        self._right_box.SelectionStart = 0

    def _on_prev(self, sender, event):
        if not self._change_positions:
            return
        self._current_change = (self._current_change - 1) % len(self._change_positions)
        self._navigate()

    def _on_next(self, sender, event):
        if not self._change_positions:
            return
        self._current_change = (self._current_change + 1) % len(self._change_positions)
        self._navigate()

    def _navigate(self):
        position = self._change_positions[self._current_change]
        self._left_box.Select(position, 0)
        self._left_box.ScrollToCaret()
        line = self._left_box.GetLineFromCharIndex(position)
        right_position = self._right_box.GetFirstCharIndexFromLine(line)
        if right_position >= 0:
            self._right_box.Select(right_position, 0)
            self._right_box.ScrollToCaret()
        self._nav.Text = "Change {0}/{1}".format(self._current_change + 1, len(self._change_positions))


def show_diff_dialog(left_text, right_text, left_title="Disk", right_title="IDE", object_name=""):
    if Form is None:
        print("Diff viewer is unavailable outside WinForms.")
        return

    max_size = max(len(left_text or ""), len(right_text or ""))
    if max_size > 100 * 1024:
        message = "The object is large ({0:.1f} KB). Open the UI diff anyway?".format(max_size / 1024.0)
        result = MessageBox.Show(message, "Large diff", MessageBoxButtons.YesNo, MessageBoxIcon.Warning)
        if result != DialogResult.Yes:
            return

    DiffViewerForm(left_text, right_text, left_title, right_title, object_name).ShowDialog()

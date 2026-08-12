# -*- coding: utf-8 -*-
"""WinForms diagram window for the CODESYS ``fsm`` command.

Shows the state machine(s) extracted from one Structured Text object as a
GDI+ diagram, with a source-ordered transition list on the left. Read-only:
it never writes to any project object.

This module is IronPython 2.7 safe (no f-strings, no annotations, no
dataclasses) and must import cleanly under CPython with ``Form = None``.
"""
from __future__ import print_function

try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, Label, Button, ListBox, ComboBox, ComboBoxStyle, Panel, MessageBox,
        MessageBoxButtons, MessageBoxIcon, FormBorderStyle,
        FormStartPosition, AnchorStyles, ControlStyles, Clipboard, Cursors
    )
    from System.Drawing import (
        Size, Point, Font, FontStyle, Color, SolidBrush, Rectangle, Pen
    )
    from System.Drawing.Drawing2D import SmoothingMode
except Exception:
    Form = None

try:
    import codesys_fmt_ui
except Exception:
    codesys_fmt_ui = None


if Form is not None:
    _BG = Color.FromArgb(30, 30, 30)
    _PANEL = Color.FromArgb(37, 37, 38)
    _TEXT = Color.FromArgb(225, 225, 225)
    _DIM = Color.FromArgb(160, 160, 160)
    _BUTTON_BG = Color.FromArgb(72, 72, 78)
    _BUTTON_BORDER = Color.FromArgb(115, 115, 125)
    _BEFORE = Color.FromArgb(245, 180, 100)
    _DIM_ALPHA = Color.FromArgb(90, 160, 160, 160)


def _style_button(form, button):
    """Style a button with the shared picker look (reused, not retyped)."""
    if codesys_fmt_ui is not None and hasattr(codesys_fmt_ui, "ObjectPickerForm"):
        # IronPython binds methods accessed through the class as unbound
        # methods, so pass a real form instance even though the shared
        # implementation only uses the button argument.
        codesys_fmt_ui.ObjectPickerForm._style_button(form, button)


def show_message(title, message, icon="info"):
    """Delegate to the fmt module's message box; do not clone it."""
    if codesys_fmt_ui is not None:
        return codesys_fmt_ui.show_message(title, message, icon)
    if Form is None:
        print("[FSM] " + str(message))
        return
    message_icon = MessageBoxIcon.Information
    if icon == "warning":
        message_icon = MessageBoxIcon.Warning
    elif icon == "error":
        message_icon = MessageBoxIcon.Error
    MessageBox.Show(message, title, MessageBoxButtons.OK, message_icon)


class _DiagramPanel(Panel if Form is not None else object):
    """A Panel that is double-buffered (a plain Panel cannot be from outside)."""

    def __init__(self):
        self.SetStyle(
            ControlStyles.OptimizedDoubleBuffer
            | ControlStyles.AllPaintingInWmPaint
            | ControlStyles.UserPaint,
            True,
        )


class FsmDiagramForm(Form if Form is not None else object):
    def __init__(self, object_label, machines, initial=0):
        self.Text = "FSM - " + (object_label or "Structured Text")
        self.Size = Size(1180, 760)
        self.MinimumSize = Size(820, 560)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor = _BG
        self.machines = machines
        self.current = initial if 0 <= initial < len(machines) else 0
        self.selected_state = None
        self.selected_transition = None
        self._transitions = self._sorted_transitions()

        header = Label()
        header.Text = object_label or "Structured Text"
        header.ForeColor = _TEXT
        header.Font = Font("Segoe UI", 12, FontStyle.Bold)
        header.Location = Point(16, 12)
        header.AutoSize = True
        self.Controls.Add(header)

        self._machine_box = None
        if len(machines) > 1:
            box = ComboBox()
            box.DropDownStyle = ComboBoxStyle.DropDownList
            box.Location = Point(16, 44)
            box.Size = Size(520, 24)
            box.BackColor = _PANEL
            box.ForeColor = _TEXT
            for index, machine in enumerate(machines):
                box.Items.Add(self._machine_caption(machine))
            box.SelectedIndex = self.current
            box.SelectedIndexChanged += self._on_machine_changed
            self.Controls.Add(box)
            self._machine_box = box

        # LEFT column: source-ordered transition list.
        caption = Label()
        caption.Text = "Transitions in scan order - a later write overrides an earlier one"
        caption.ForeColor = _DIM
        caption.Location = Point(16, 78)
        caption.AutoSize = True
        self.Controls.Add(caption)

        self._list = ListBox()
        self._list.Location = Point(16, 100)
        self._list.Size = Size(380, 500)
        self._list.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left
        self._list.BackColor = _PANEL
        self._list.ForeColor = _TEXT
        self._list.Font = Font("Consolas", 9)
        self._list.SelectedIndexChanged += self._on_transition_selected
        self.Controls.Add(self._list)
        self._refresh_transition_list()

        self._guard = Label()
        self._guard.ForeColor = _DIM
        self._guard.Location = Point(16, 606)
        self._guard.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        self._guard.AutoSize = True
        self.Controls.Add(self._guard)

        # RIGHT: the diagram panel.
        self._diagram = _DiagramPanel()
        self._diagram.Location = Point(410, 78)
        self._diagram.Anchor = (
            AnchorStyles.Top | AnchorStyles.Bottom
            | AnchorStyles.Left | AnchorStyles.Right
        )
        self._diagram.BackColor = _BG
        self._diagram.AutoScroll = True
        self._diagram.Paint += self._paint_diagram
        self._diagram.MouseClick += self._on_diagram_click
        self.Controls.Add(self._diagram)

        # BOTTOM: buttons right-aligned.
        close_button = Button()
        close_button.Text = "Close"
        close_button.Size = Size(90, 30)
        close_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        close_button.Click += self._close
        _style_button(self, close_button)
        self.Controls.Add(close_button)
        self._close_button = close_button

        copy_button = Button()
        copy_button.Text = "Copy as mermaid"
        copy_button.Size = Size(140, 30)
        copy_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        copy_button.Click += self._copy_mermaid
        _style_button(self, copy_button)
        self.Controls.Add(copy_button)
        self._copy_button = copy_button

        warnings = self._current_machine().warnings
        self._warnings_label = Label()
        self._warnings_label.Text = "{0} warning(s)".format(len(warnings))
        self._warnings_label.ForeColor = _DIM
        self._warnings_label.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        self._warnings_label.AutoSize = True
        self._warnings_label.Cursor = Cursors.Hand
        self._warnings_label.Click += self._show_warnings
        self.Controls.Add(self._warnings_label)

        self.Resize += self._layout
        self._layout()
        self._update_warnings_label()

    def _current_machine(self):
        return self.machines[self.current]

    def _machine_caption(self, machine):
        return "CASE {0}  -  {1} states, {2} transitions".format(
            machine.selector, len(machine.states), len(machine.transitions)
        )

    def _sorted_transitions(self):
        return sorted(self._current_machine().transitions, key=lambda t: t.offset)

    def _refresh_transition_list(self):
        self._list.BeginUpdate()
        try:
            self._list.Items.Clear()
            for transition in self._transitions:
                source = transition.source if transition.source is not None else "(any)"
                self._list.Items.Add("{0}  ->  {1}".format(source, transition.target))
        finally:
            self._list.EndUpdate()

    def _on_machine_changed(self, sender, event):
        self.current = self._machine_box.SelectedIndex
        self.selected_state = None
        self.selected_transition = None
        self._transitions = self._sorted_transitions()
        self._refresh_transition_list()
        self._guard.Text = ""
        self._update_warnings_label()
        self._diagram.Invalidate()

    def _on_transition_selected(self, sender, event):
        index = self._list.SelectedIndex
        if index < 0 or index >= len(self._transitions):
            return
        transition = self._transitions[index]
        self.selected_transition = transition
        self.selected_state = None
        self._guard.Text = transition.guard or "(no guard)"
        self._diagram.Invalidate()
        self._scroll_to_source(transition)

    def _on_diagram_click(self, sender, event):
        state = self._state_at(event.Location)
        if state is None:
            self.selected_state = None
            self.selected_transition = None
            self._list.ClearSelected()
            self._guard.Text = ""
        else:
            self.selected_state = state.label
            self.selected_transition = None
            self._list.ClearSelected()
            self._guard.Text = ""
        self._diagram.Invalidate()

    def _copy_mermaid(self, sender, event):
        from cts_shared.st.fsm_mermaid import to_mermaid
        machine = self._current_machine()
        text = to_mermaid(machine, title=self.Text)
        try:
            Clipboard.SetText(text)
        except Exception:
            show_message("FSM", "Could not copy to the clipboard.", "error")
            return
        self._copy_button.Text = "Copied"
        self._copy_button.Invalidate()

    def _close(self, sender, event):
        self.Close()

    def _show_warnings(self, sender, event):
        machine = self._current_machine()
        if not machine.warnings:
            show_message("FSM", "No warnings for this state machine.", "info")
            return
        lines = []
        for offset, message in machine.warnings:
            lines.append("offset {0}: {1}".format(offset, message))
        show_message("FSM", "\n".join(lines), "warning")

    def _update_warnings_label(self):
        count = len(self._current_machine().warnings)
        self._warnings_label.Text = "{0} warning(s)".format(count)

    def _layout(self, sender=None, event=None):
        width = self.ClientSize.Width
        height = self.ClientSize.Height
        margin = 16
        button_y = max(0, height - 42)
        self._close_button.Location = Point(
            width - margin - self._close_button.Width, button_y
        )
        self._copy_button.Location = Point(
            self._close_button.Left - 10 - self._copy_button.Width, button_y
        )
        self._warnings_label.Location = Point(margin, button_y + 6)
        self._list.Size = Size(380, max(100, button_y - 100 - 6))
        self._guard.Location = Point(margin, button_y - 24)
        self._diagram.Size = Size(
            max(100, width - 410 - margin), max(100, button_y - 78)
        )

    # -- diagram geometry ---------------------------------------------------

    _BOX_X = 40
    _BOX_W = 260
    _BOX_H = 38
    _GAP = 30

    def _row_count(self):
        machine = self._current_machine()
        has_any = any(t.source is None for t in machine.transitions)
        return len(machine.states) + (1 if has_any else 0)

    def _row_y(self, row):
        return 20 + row * (self._BOX_H + self._GAP)

    def _state_row(self, label):
        machine = self._current_machine()
        has_any = any(t.source is None for t in machine.transitions)
        offset = 1 if has_any else 0
        for index, state in enumerate(machine.states):
            if state.label == label:
                return index + offset
        return None

    def _any_row(self):
        return 0 if any(t.source is None for t in self._current_machine().transitions) else None

    def _state_at(self, point):
        machine = self._current_machine()
        has_any = any(t.source is None for t in machine.transitions)
        if has_any:
            if self._box_contains(point, 0):
                return None  # "(any state)" is not a selectable state
        for state in machine.states:
            row = self._state_row(state.label)
            if row is not None and self._box_contains(point, row):
                return state
        return None

    def _box_contains(self, point, row):
        x = self._BOX_X
        y = self._row_y(row)
        return (
            x <= point.X <= x + self._BOX_W
            and y <= point.Y <= y + self._BOX_H
        )

    def _scroll_to_source(self, transition):
        row = None
        if transition.source is not None:
            row = self._state_row(transition.source)
        else:
            row = self._any_row()
        if row is None:
            return
        y = self._row_y(row)
        self._diagram.AutoScrollPosition = Point(
            self._diagram.AutoScrollPosition.X, y
        )

    # -- painting -----------------------------------------------------------

    def _paint_diagram(self, sender, event):
        graphics = event.Graphics
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        machine = self._current_machine()
        has_any = any(t.source is None for t in machine.transitions)

        # Content size for scrolling.
        rows = self._row_count()
        content_height = self._row_y(rows - 1) + self._BOX_H + 20
        content_width = self._BOX_X + self._BOX_W + 200
        self._diagram.AutoScrollMinSize = Size(content_width, content_height)

        # Draw the "(any state)" box first.
        if has_any:
            self._draw_box(graphics, 0, "(any state)", _DIM)

        for state in machine.states:
            row = self._state_row(state.label)
            self._draw_box(graphics, row, state.label, _TEXT)

        # Edges.
        for transition in machine.transitions:
            self._draw_edge(graphics, transition, has_any)

    def _draw_box(self, graphics, row, label, color):
        x = self._BOX_X
        y = self._row_y(row)
        rect = Rectangle(x, y, self._BOX_W, self._BOX_H)
        fill = SolidBrush(_PANEL)
        try:
            graphics.FillRectangle(fill, rect)
        finally:
            fill.Dispose()
        pen = Pen(_BUTTON_BORDER, 1)
        try:
            graphics.DrawRectangle(pen, rect)
        finally:
            pen.Dispose()
        text = self._truncate(graphics, label, self._BOX_W - 12)
        brush = SolidBrush(color)
        try:
            size = graphics.MeasureString(text, self._label_font())
            graphics.DrawString(
                text, self._label_font(), brush,
                x + (self._BOX_W - size.Width) / 2,
                y + (self._BOX_H - size.Height) / 2,
            )
        finally:
            brush.Dispose()

    def _label_font(self):
        return Font("Consolas", 9)

    def _truncate(self, graphics, text, max_width):
        if graphics.MeasureString(text, self._label_font()).Width <= max_width:
            return text
        ellipsis = "..."
        while text and graphics.MeasureString(text + ellipsis, self._label_font()).Width > max_width:
            text = text[:-1]
        return text + ellipsis

    def _draw_edge(self, graphics, transition, has_any):
        if transition.source is None:
            source_row = self._any_row()
        else:
            source_row = self._state_row(transition.source)
        target_row = self._state_row(transition.target)
        if source_row is None or target_row is None:
            return

        highlighted = (
            self.selected_transition is transition
            or (
                self.selected_state is not None
                and (
                    transition.source == self.selected_state
                    or transition.target == self.selected_state
                )
            )
        )

        if self.selected_state is not None and not highlighted:
            color = _DIM_ALPHA
        elif self.selected_transition is not None and not highlighted:
            color = _DIM_ALPHA
        else:
            color = _BEFORE if highlighted else _DIM

        if transition.source is not None and transition.source == transition.target:
            self._draw_self_loop(graphics, source_row, color)
            return

        x1 = self._BOX_X + self._BOX_W
        y1 = self._row_y(source_row) + self._BOX_H / 2
        x2 = self._BOX_X + self._BOX_W
        y2 = self._row_y(target_row) + self._BOX_H / 2
        bulge = 40 + 18 * min(6, abs(target_row - source_row))
        mid_x = x1 + bulge

        pen = Pen(color, 2)
        try:
            graphics.DrawBezier(
                pen,
                Point(x1, y1),
                Point(mid_x, y1),
                Point(mid_x, y2),
                Point(x2, y2),
            )
        finally:
            pen.Dispose()
        self._draw_arrowhead(graphics, x2, y2, color)

    def _draw_self_loop(self, graphics, row, color):
        x = self._BOX_X + self._BOX_W
        y = self._row_y(row) + self._BOX_H / 2
        pen = Pen(color, 2)
        try:
            graphics.DrawEllipse(pen, x, y - 12, 26, 24)
        finally:
            pen.Dispose()
        self._draw_arrowhead(graphics, x + 26, y, color)

    def _draw_arrowhead(self, graphics, x, y, color):
        brush = SolidBrush(color)
        try:
            points = [
                Point(x, y),
                Point(x - 7, y - 4),
                Point(x - 7, y + 4),
            ]
            graphics.FillPolygon(brush, points)
        finally:
            brush.Dispose()


def show_fsm_diagram(object_label, machines, initial=0):
    if Form is None:
        return
    form = FsmDiagramForm(object_label, machines, initial=initial)
    form.ShowDialog()

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
    import System
    from System.Windows.Forms import (
        Form, Label, Button, ListBox, ComboBox, ComboBoxStyle, Panel, MessageBox,
        MessageBoxButtons, MessageBoxIcon, FormBorderStyle, FlatStyle,
        FormStartPosition, AnchorStyles, ControlStyles, Clipboard, Cursors,
        Timer, ToolTip
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

from cts_shared.st import fsm_layout


if Form is not None:
    _BG = Color.FromArgb(30, 30, 30)
    _PANEL = Color.FromArgb(37, 37, 38)
    _TEXT = Color.FromArgb(225, 225, 225)
    _DIM = Color.FromArgb(160, 160, 160)
    _BUTTON_BG = Color.FromArgb(72, 72, 78)
    _BUTTON_BORDER = Color.FromArgb(115, 115, 125)
    _BEFORE = Color.FromArgb(245, 180, 100)
    _DIM_ALPHA = Color.FromArgb(90, 160, 160, 160)
    _STEP_FILL = Color.FromArgb(45, 48, 52)
    _STEP_BORDER = Color.FromArgb(150, 155, 165)
    _LINK = Color.FromArgb(150, 155, 165)
    _GUARD = Color.FromArgb(150, 190, 230)
    _PRIORITY = Color.FromArgb(235, 140, 120)
    _DIVIDER = Color.FromArgb(95, 100, 108)
    _CHIP_FILL = Color.FromArgb(38, 41, 45)
    _JUMP = Color.FromArgb(215, 170, 110)

    # A GRAFCET bar is perpendicular to its link. A vertical bar crossing a
    # horizontal link is drawn shorter than a horizontal one so it does not
    # overshoot a self-loop.
    _BAR_V_HALF = 9
    _ARROW_LEN = 8
    _ARROW_HALF = 5


def _style_button(button):
    """Style a diagram button without crossing IronPython class boundaries."""
    if Form is None:
        return
    button.BackColor = _BUTTON_BG
    button.ForeColor = _TEXT
    button.FlatStyle = FlatStyle.Flat
    button.FlatAppearance.BorderColor = _BUTTON_BORDER
    button.FlatAppearance.BorderSize = 1
    button.UseVisualStyleBackColor = False


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


class _Pt(object):
    """A CLR-free point, so the diagram geometry stays testable headless."""

    def __init__(self, x, y):
        self.X = x
        self.Y = y


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
        self._font_step = Font("Consolas", 9)
        self._font_num = Font("Consolas", 9, FontStyle.Bold)
        self._font_guard = Font("Consolas", 8.25)
        self._grafcet = None
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
        self._list.HorizontalScrollbar = True
        self._list.SelectedIndexChanged += self._on_transition_selected
        self.Controls.Add(self._list)
        self._refresh_transition_list()

        self._guard = Label()
        self._guard.ForeColor = _DIM
        self._guard.Location = Point(16, 606)
        self._guard.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        self._guard.AutoSize = False
        self._guard.Font = Font("Consolas", 8.25)
        self.Controls.Add(self._guard)
        self._guard_tip = ToolTip()

        # RIGHT: the diagram panel.
        self._diagram_caption = Label()
        self._diagram_caption.ForeColor = _DIM
        self._diagram_caption.Location = Point(410, 78)
        self._diagram_caption.AutoSize = True
        self.Controls.Add(self._diagram_caption)

        self._diagram = _DiagramPanel()
        self._diagram.Location = Point(410, 100)
        self._diagram.Anchor = (
            AnchorStyles.Top | AnchorStyles.Bottom
            | AnchorStyles.Left | AnchorStyles.Right
        )
        self._diagram.BackColor = _BG
        self._diagram.AutoScroll = True
        self._diagram.Paint += self._paint_diagram
        self._diagram.MouseClick += self._on_diagram_click
        self.Controls.Add(self._diagram)
        self._rebuild_grafcet()
        self._refresh_transition_list()

        # BOTTOM: buttons right-aligned.
        close_button = Button()
        close_button.Text = "Close"
        close_button.Size = Size(90, 30)
        close_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        close_button.Click += self._close
        _style_button(close_button)
        self.Controls.Add(close_button)
        self._close_button = close_button

        copy_button = Button()
        copy_button.Text = "Copy as mermaid"
        copy_button.Size = Size(140, 30)
        copy_button.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        copy_button.Click += self._copy_mermaid
        _style_button(copy_button)
        self.Controls.Add(copy_button)
        self._copy_button = copy_button

        self._copy_reset = Timer()
        self._copy_reset.Interval = 1200
        self._copy_reset.Tick += self._reset_copy_caption

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
        """Source-ordered transitions, with the shared enum prefix stripped."""
        prefix = self._grafcet.prefix if self._grafcet is not None else ""
        self._list.BeginUpdate()
        try:
            self._list.Items.Clear()
            for transition in self._transitions:
                if transition.source is None:
                    source = "any"
                else:
                    source = fsm_layout.strip_prefix(transition.source, prefix)
                target = fsm_layout.strip_prefix(transition.target, prefix)
                self._list.Items.Add("{0}  ->  {1}".format(source, target))
        finally:
            self._list.EndUpdate()

    def _on_machine_changed(self, sender, event):
        self.current = self._machine_box.SelectedIndex
        self.selected_state = None
        self.selected_transition = None
        self._transitions = self._sorted_transitions()
        self._rebuild_grafcet()
        self._refresh_transition_list()
        self._guard.Text = ""
        self._update_warnings_label()
        self._diagram.AutoScrollPosition = Point(0, 0)
        self._diagram.Invalidate()

    def _on_transition_selected(self, sender, event):
        index = self._list.SelectedIndex
        if index < 0 or index >= len(self._transitions):
            return
        transition = self._transitions[index]
        self.selected_transition = transition
        self.selected_state = None
        text = transition.guard or "=1  (unconditional)"
        self._guard.Text = text
        self._guard_tip.SetToolTip(self._guard, text)
        self._diagram.Invalidate()
        self._scroll_to_source(transition)

    def _on_diagram_click(self, sender, event):
        """A click selects a transition when it lands on a link or its
        receptivity, and a step otherwise."""
        if self._grafcet is None:
            return
        point = self._to_content(event.Location)
        link = self._grafcet.link_at(point.X, point.Y)
        if link is not None:
            for index, transition in enumerate(self._transitions):
                if transition is link.transition:
                    # Routing through the list keeps one selection path: it
                    # fills the guard label and scrolls the diagram.
                    self._list.SelectedIndex = index
                    return
        step = self._grafcet.step_at(point.X, point.Y)
        self.selected_transition = None
        self._list.ClearSelected()
        self._guard.Text = ""
        self._guard_tip.SetToolTip(self._guard, "")
        self.selected_state = step.full_label if step is not None else None
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
        self._copy_reset.Stop()
        self._copy_reset.Start()

    def _reset_copy_caption(self, sender, event):
        self._copy_reset.Stop()
        self._copy_button.Text = "Copy as mermaid"

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
        guard_w = max(120, self._copy_button.Left - 10 - margin)
        # One line only: at 30px the label wrapped and AutoEllipsis then
        # trimmed the second line, so a long condition showed its middle
        # instead of its start.
        self._guard.Size = Size(guard_w, 18)
        self._guard.Location = Point(margin, button_y - 26)
        try:
            self._guard.AutoEllipsis = True
        except Exception:
            pass
        self._diagram.Size = Size(
            max(100, width - 410 - margin), max(100, button_y - 100)
        )

    # -- diagram geometry ---------------------------------------------------

    def _to_content(self, point):
        """Client coordinates -> diagram coordinates.

        ``AutoScrollPosition`` reads back as zero or negative, so subtracting
        it moves a click down into the scrolled-away part of the diagram.
        """
        scroll = self._diagram.AutoScrollPosition
        return _Pt(point.X - scroll.X, point.Y - scroll.Y)

    def _scroll_to_source(self, transition):
        # A priority transition has no source step, so scroll to where it lands.
        label = transition.source
        if label is None:
            label = transition.target
        step = self._grafcet.step_for(label)
        if step is None:
            return
        # The getter returns a negative offset but the setter expects a
        # positive one, so the current X has to be flipped back on the way in.
        self._diagram.AutoScrollPosition = Point(
            -self._diagram.AutoScrollPosition.X, max(0, step.y - 40)
        )

    def _update_scroll_size(self):
        """Publish the diagram extent so the panel can size its scrollbars."""
        if self._grafcet is None:
            self._diagram.AutoScrollMinSize = Size(0, 0)
            return
        self._diagram.AutoScrollMinSize = Size(
            self._grafcet.width, self._grafcet.height
        )

    def _measures(self):
        """GDI+ text measurement for the layout, or (None, None, None) when the
        panel has no device context yet -- the layout then falls back to its
        own estimate."""
        try:
            graphics = self._diagram.CreateGraphics()
        except Exception:
            return None, None, None

        def measure(text):
            if not text:
                return 0
            return int(graphics.MeasureString(text, self._font_step).Width) + 2

        def guard(text):
            if not text:
                return 0
            return int(graphics.MeasureString(text, self._font_guard).Width) + 2

        return measure, guard, graphics

    def _rebuild_grafcet(self):
        measure, guard, graphics = self._measures()
        try:
            self._grafcet = fsm_layout.build_layout(
                self._current_machine(), measure, guard
            )
        finally:
            if graphics is not None:
                graphics.Dispose()
        machine = self._current_machine()
        caption = "CASE {0} OF".format(machine.selector)
        if self._grafcet.prefix:
            # The enum prefix is stripped from every step so the labels fit;
            # say once what was stripped.
            caption += "     " + self._grafcet.prefix + "*"
        self._diagram_caption.Text = caption
        self._update_scroll_size()

    # -- painting -----------------------------------------------------------

    def _paint_diagram(self, sender, event):
        graphics = event.Graphics
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        # Everything below is drawn in diagram coordinates; the panel only
        # scrolls owner-drawn content if the origin is shifted by hand.
        scroll = self._diagram.AutoScrollPosition
        graphics.TranslateTransform(scroll.X, scroll.Y)
        if self._grafcet is None:
            return
        if self._grafcet.has_any:
            self._draw_any_block(graphics)
        for chip in self._grafcet.chips:
            self._draw_chip(graphics, chip)
        for step in self._grafcet.steps:
            self._draw_step(graphics, step)
        for link in self._grafcet.links:
            self._draw_link(graphics, link)

    def _draw_any_block(self, graphics):
        x, y, w, h = self._grafcet.any_box
        self._fill_rect(graphics, _PANEL, x, y, w, h)
        self._stroke_rect(graphics, _PRIORITY, 2, x, y, w, h)
        self._draw_centred(graphics, "any", self._font_num, _PRIORITY, x, y, w, h)
        self._draw_text(graphics, "priority - written outside the CASE",
                        self._font_guard, _DIM, x, y - 18)

    def _draw_chip(self, graphics, chip):
        """A priority transition's target, drawn small so the reader sees which
        block it lands in without having to hunt for the number."""
        self._fill_rect(graphics, _CHIP_FILL, chip.x, chip.y, chip.w, chip.h)
        self._stroke_rect(graphics, _PRIORITY, 1, chip.x, chip.y, chip.w, chip.h)
        divider_x = chip.x + fsm_layout.NUM_W
        self._draw_line(graphics, _DIVIDER, 1, divider_x, chip.y,
                        divider_x, chip.bottom)
        self._draw_centred(graphics, str(chip.number), self._font_num, _TEXT,
                           chip.x, chip.y, fsm_layout.NUM_W, chip.h)
        self._draw_text(graphics, chip.label, self._font_step, _TEXT,
                        divider_x + 10, chip.y + (chip.h - fsm_layout.TEXT_H) // 2)

    def _draw_step(self, graphics, step):
        selected = (self.selected_state == step.full_label)
        border = _BEFORE if selected else _STEP_BORDER
        self._fill_rect(graphics, _STEP_FILL, step.x, step.y, step.w, step.h)
        self._stroke_rect(graphics, border, 2 if selected else 1,
                          step.x, step.y, step.w, step.h)
        if step.initial:
            # IEC 60848 marks the initial step with a double border.
            self._stroke_rect(graphics, border, 1, step.x + 3, step.y + 3,
                              step.w - 6, step.h - 6)
        divider_x = step.x + fsm_layout.NUM_W
        self._draw_line(graphics, _DIVIDER, 1, divider_x, step.y,
                        divider_x, step.bottom)
        self._draw_centred(graphics, str(step.number), self._font_num, _TEXT,
                           step.x, step.y, fsm_layout.NUM_W, step.h)
        self._draw_text(graphics, step.label, self._font_step, _TEXT,
                        divider_x + 10, step.y + (step.h - fsm_layout.TEXT_H) // 2)
        if step.priority:
            self._draw_arrowhead(graphics, step.x - 4, step.cy, "right", _PRIORITY)
        if step.inbound:
            # This step is reached by a connector, so nothing points at it on
            # the page; name the steps that jump here.
            text = ", ".join(str(number) for number in step.inbound)
            self._draw_text(graphics, text, self._font_guard, _JUMP,
                            step.x - fsm_layout.INBOUND_W,
                            step.y + (step.h - fsm_layout.TEXT_H) // 2)

    def _draw_link(self, graphics, link):
        colour = self._link_colour(link)
        points = System.Array[Point](
            [Point(int(px), int(py)) for px, py in link.points]
        )
        pen = Pen(colour, 2)
        try:
            graphics.DrawLines(pen, points)
        finally:
            pen.Dispose()
        if link.bar is not None:
            bx, by, orientation = link.bar
            if orientation == "h":
                self._draw_line(graphics, colour, 3, bx - fsm_layout.BAR_HALF,
                                by, bx + fsm_layout.BAR_HALF, by)
            else:
                self._draw_line(graphics, colour, 3, bx, by - _BAR_V_HALF,
                                bx, by + _BAR_V_HALF)
        if link.arrow is not None:
            ax, ay, direction = link.arrow
            self._draw_arrowhead(graphics, ax, ay, direction, colour)
        if link.guard_at:
            gx, gy = link.guard_at
            self._draw_text(graphics, link.guard_text, self._font_guard,
                            self._text_colour(link, _GUARD), gx, gy)
        if link.note_at and link.note_text:
            nx, ny = link.note_at
            self._draw_text(graphics, link.note_text, self._font_guard,
                            _JUMP, nx, ny)

    def _link_colour(self, link):
        """Selected first, then dimmed when something else is selected."""
        if link.kind == "global":
            base = _PRIORITY
        elif link.kind == "jump":
            base = _JUMP
        else:
            base = _LINK
        if self.selected_transition is link.transition:
            return _BEFORE
        if self.selected_state is not None:
            source = link.transition.source
            if source == self.selected_state or link.transition.target == self.selected_state:
                return _BEFORE
            return _DIM_ALPHA
        if self.selected_transition is not None:
            return _DIM_ALPHA
        return base

    def _text_colour(self, link, normal):
        colour = self._link_colour(link)
        if colour.Equals(_DIM_ALPHA):
            return _DIM_ALPHA
        if colour.Equals(_BEFORE):
            return _BEFORE
        return normal

    # -- small drawing primitives ------------------------------------------

    def _fill_rect(self, graphics, colour, x, y, w, h):
        brush = SolidBrush(colour)
        try:
            graphics.FillRectangle(brush, int(x), int(y), int(w), int(h))
        finally:
            brush.Dispose()

    def _stroke_rect(self, graphics, colour, width, x, y, w, h):
        pen = Pen(colour, width)
        try:
            graphics.DrawRectangle(pen, int(x), int(y), int(w), int(h))
        finally:
            pen.Dispose()

    def _draw_line(self, graphics, colour, width, x1, y1, x2, y2):
        pen = Pen(colour, width)
        try:
            graphics.DrawLine(pen, int(x1), int(y1), int(x2), int(y2))
        finally:
            pen.Dispose()

    def _draw_text(self, graphics, text, font, colour, x, y):
        brush = SolidBrush(colour)
        try:
            graphics.DrawString(text, font, brush, int(x), int(y))
        finally:
            brush.Dispose()

    def _draw_centred(self, graphics, text, font, colour, x, y, w, h):
        """DrawString centred inside the box (x, y, w, h) using MeasureString."""
        brush = SolidBrush(colour)
        try:
            size = graphics.MeasureString(text, font)
            graphics.DrawString(
                text, font, brush,
                int(x) + (int(w) - size.Width) / 2,
                int(y) + (int(h) - size.Height) / 2,
            )
        finally:
            brush.Dispose()

    def _draw_arrowhead(self, graphics, x, y, direction, colour):
        """Filled triangle with its TIP at (x, y), pointing *direction*."""
        x = int(x)
        y = int(y)
        if direction == "left":
            points = [(x, y), (x + _ARROW_LEN, y - _ARROW_HALF),
                      (x + _ARROW_LEN, y + _ARROW_HALF)]
        elif direction == "right":
            points = [(x, y), (x - _ARROW_LEN, y - _ARROW_HALF),
                      (x - _ARROW_LEN, y + _ARROW_HALF)]
        elif direction == "down":
            points = [(x, y), (x - _ARROW_HALF, y - _ARROW_LEN),
                      (x + _ARROW_HALF, y - _ARROW_LEN)]
        else:  # up
            points = [(x, y), (x - _ARROW_HALF, y + _ARROW_LEN),
                      (x + _ARROW_HALF, y + _ARROW_LEN)]
        brush = SolidBrush(colour)
        try:
            arr = System.Array[Point](
                [Point(int(px), int(py)) for px, py in points]
            )
            graphics.FillPolygon(brush, arr)
        finally:
            brush.Dispose()


def show_fsm_diagram(object_label, machines, initial=0):
    if Form is None:
        return
    form = FsmDiagramForm(object_label, machines, initial=initial)
    form.ShowDialog()

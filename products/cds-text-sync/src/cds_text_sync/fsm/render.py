"""FSM rendering: GRAFCET geometry, safe standalone SVG, and mermaid text.

CPython 3.11 only, like the rest of the package - the CODESYS host never
imports this module.  Everything consumes the JSON-safe machine payload dict
produced by ``model.machine_payload`` and never looks at source text.

``layout_payload`` adapts a payload back into the shared model, runs
``cts_shared.st.fsm_layout.build_layout``, and returns the computed geometry
as a JSON-safe dict.  ``to_svg`` draws the same shapes in the same places as
the WinForms GDI+ reference renderer (``ide_bridge.codesys_fsm_ui``) as a
standalone SVG document.  ``to_mermaid_text`` forwards to the shared mermaid
renderer.

Stable selection: every element a link draws carries ``data-transition`` with
the payload-relative index of that transition (matching ``transition_index``
in :func:`layout_payload`), and every element a step draws carries
``data-state`` with the step's full source label, so the frontend can map a
click back to a transition row or state row.

SAFETY: every string that originates in the ST source (state labels, guard
text, note text, the title) is XML-escaped before it is emitted.  The output
never contains a raw ``<``, ``>``, ``&`` or ``"`` from source-derived text,
never emits ``<script>``, ``<foreignObject>``, event-handler attributes or
``xlink:href``, so the SVG is safe to embed anywhere.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from cts_shared.st import fsm_layout
from cts_shared.st.fsm_layout import build_layout
from cts_shared.st.fsm_mermaid import to_mermaid

from .model import machine_from_payload

# Arrow geometry mirrors codesys_fsm_ui._draw_arrowhead (tip at (x, y)).
_BAR_V_HALF = 9
_ARROW_LEN = 8
_ARROW_HALF = 5

# Light-background palette.  Colours need not match the WinForms window;
# the shapes and coordinates do.
_BG = "#f7f7f5"
_TEXT = "#1c1c1c"
_DIM = "#555555"
_DIVIDER = "#b8b8b8"
_STEP_FILL = "#ffffff"
_STEP_STROKE = "#3a3a3a"
_LINK = "#4a5568"
_GUARD = "#2a5db0"
_PRIORITY = "#b23a2e"
_CHIP_FILL = "#fbf1f0"
_JUMP = "#a35c12"


def _escape(text):
    """XML-escape source-derived text for safe SVG output.

    ``&``, ``<`` and ``>`` are escaped for text nodes; ``"`` as well, so the
    result is safe to interpolate into either an attribute value or text
    content.  A hostile label or guard therefore cannot inject markup or a
    script.
    """
    return escape(str(text), {'"': "&quot;"})


# ---------------------------------------------------------------------------
# layout_payload: the geometry as JSON-safe data
# ---------------------------------------------------------------------------


def layout_payload(payload, title=None):
    """Return the GRAFCET geometry for a machine *payload* as a JSON-safe dict.

    The dict carries width, height, prefix, dropped, columns and the optional
    ``any_box`` plus lists for steps, chips and links.  Every coordinate is a
    plain int; ``points``/``bar``/``guard_at``/``arrow``/``note_at`` tuples are
    emitted as lists of ints (orientation strings kept as str) so
    ``json.dumps`` round-trips exactly.

    *title* is accepted for symmetry with :func:`to_svg` and
    :func:`to_mermaid_text`; it does not affect the geometry.
    """
    machine = machine_from_payload(payload)
    layout = build_layout(machine)
    # Transition rows are payload-relative, not link-relative: the frontend
    # indexes transition rows by the payload's ``transitions`` order (source
    # offset order), while ``layout.links`` reorders by drawing kind and drops
    # transitions whose endpoints are not known states.  Resolve the index by
    # object identity against the adapter's transitions, which
    # ``machine_from_payload`` appends in exactly the payload's order, so the
    # index matches the position of the same transition in ``payload``.
    index_by_id = {id(t): i for i, t in enumerate(machine.transitions)}
    return {
        "width": int(layout.width),
        "height": int(layout.height),
        "prefix": layout.prefix,
        "dropped": int(layout.dropped),
        "columns": int(layout.columns),
        "any_box": (
            None if layout.any_box is None else [int(v) for v in layout.any_box]
        ),
        "steps": [_step_dict(step) for step in layout.steps],
        "chips": [_chip_dict(chip) for chip in layout.chips],
        "links": [_link_dict(link, index_by_id) for link in layout.links],
    }


def _step_dict(step):
    return {
        "number": int(step.number),
        "label": step.label,
        "full_label": step.full_label,
        "x": int(step.x),
        "y": int(step.y),
        "w": int(step.w),
        "h": int(step.h),
        "initial": bool(step.initial),
        "priority": bool(step.priority),
        "col": int(step.col),
        "row": int(step.row),
        "inbound": [int(number) for number in step.inbound],
    }


def _chip_dict(chip):
    return {
        "number": int(chip.number),
        "label": chip.label,
        "x": int(chip.x),
        "y": int(chip.y),
        "w": int(chip.w),
        "h": int(chip.h),
    }


def _link_dict(link, index_by_id):
    return {
        "kind": link.kind,
        "transition_index": index_by_id.get(id(link.transition)),
        "points": [[int(px), int(py)] for px, py in link.points],
        "bar": (
            None
            if link.bar is None
            else [int(link.bar[0]), int(link.bar[1]), link.bar[2]]
        ),
        "guard_text": link.guard_text,
        "guard_at": (
            None
            if link.guard_at is None
            else [int(link.guard_at[0]), int(link.guard_at[1])]
        ),
        "guard_w": int(link.guard_w),
        "arrow": (
            None
            if link.arrow is None
            else [int(link.arrow[0]), int(link.arrow[1]), link.arrow[2]]
        ),
        "note_text": link.note_text,
        "note_at": (
            None
            if link.note_at is None
            else [int(link.note_at[0]), int(link.note_at[1])]
        ),
        "note_w": int(link.note_w),
    }


# ---------------------------------------------------------------------------
# to_svg: the standalone, safe SVG document
# ---------------------------------------------------------------------------


def to_svg(payload, title=None):
    """Render a machine *payload* as a standalone, safe SVG document.

    Draws the same GRAFCET shapes at the same coordinates as the WinForms
    reference renderer: step boxes (double-bordered when initial) with their
    number and label, chips, links as polylines with their guard bars,
    arrowheads, guard and note text, and the "any" box when present.  When
    *title* is given it is emitted as an SVG ``<title>`` element and as a text
    label at the top.  A machine with no states still yields a valid minimal
    ``<svg>``.
    """
    machine = machine_from_payload(payload)
    layout = build_layout(machine)
    # Same payload-relative index map as layout_payload (see its docstring for
    # why the index is not the layout.links position): every element a link
    # draws carries data-transition so a click maps straight back to the
    # payload transition row.
    index_by_id = {id(t): i for i, t in enumerate(machine.transitions)}
    width = int(layout.width)
    height = int(layout.height)
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    out.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}" '
        'viewBox="0 0 {0} {1}">'.format(width, height)
    )
    if title:
        out.append("<title>{0}</title>".format(_escape(title)))
    out.append(
        '<rect x="0" y="0" width="{0}" height="{1}" fill="{2}"/>'.format(
            width, height, _BG
        )
    )
    if title:
        out.append(_text(10, 14, title, _TEXT, 16))
    if layout.has_any:
        out.append(_draw_any(layout.any_box))
    for chip in layout.chips:
        out.append(_draw_chip(chip))
    for step in layout.steps:
        out.append(_draw_step(step))
    for link in layout.links:
        out.append(_draw_link(link, index_by_id.get(id(link.transition))))
    out.append("</svg>")
    return "\n".join(out)


def _draw_any(any_box):
    """The priority block: an "any" box whose stem drops onto the rail."""
    x, y, w, h = (int(v) for v in any_box)
    out = [_rect(x, y, w, h, _CHIP_FILL, _PRIORITY, 2)]
    out.append(_centre_text(x, y, w, h, "any", _PRIORITY, 13))
    out.append(_text(x, y - 18, "priority - written outside the CASE", _DIM, 11))
    return "\n".join(out)


def _draw_chip(chip):
    """A priority transition's target, drawn as a small numbered box."""
    out = [_rect(chip.x, chip.y, chip.w, chip.h, _CHIP_FILL, _PRIORITY, 1)]
    divider_x = int(chip.x) + fsm_layout.NUM_W
    out.append(_line(divider_x, chip.y, divider_x,
                     int(chip.y) + int(chip.h), _DIVIDER, 1))
    out.append(_centre_text(chip.x, chip.y, fsm_layout.NUM_W, chip.h,
                            str(chip.number), _TEXT, 13))
    out.append(_text(divider_x + 10,
                     int(chip.y) + (int(chip.h) - fsm_layout.TEXT_H) // 2,
                     chip.label, _TEXT, 13))
    return "\n".join(out)


def _draw_step(step):
    """One numbered GRAFCET step box, double-bordered when it is initial.

    Every element carries ``data-state`` with the step's full (unprefixed)
    source label, XML-escaped, so the frontend can map a click back to the
    payload state row regardless of which visual the user hit.
    """
    data_state = step.full_label
    out = [_rect(step.x, step.y, step.w, step.h, _STEP_FILL, _STEP_STROKE, 1,
                 data_state=data_state)]
    if step.initial:
        out.append(_rect(step.x + 3, step.y + 3, step.w - 6, step.h - 6,
                         _STEP_FILL, _STEP_STROKE, 1, data_state=data_state))
    divider_x = int(step.x) + fsm_layout.NUM_W
    out.append(_line(divider_x, step.y, divider_x,
                     int(step.y) + int(step.h), _DIVIDER, 1,
                     data_state=data_state))
    out.append(_centre_text(step.x, step.y, fsm_layout.NUM_W, step.h,
                            str(step.number), _TEXT, 13,
                            data_state=data_state))
    out.append(_text(divider_x + 10,
                     int(step.y) + (int(step.h) - fsm_layout.TEXT_H) // 2,
                     step.label, _TEXT, 13, data_state=data_state))
    if step.priority:
        out.append(_arrowhead(int(step.x) - 4,
                              int(step.y) + int(step.h) // 2,
                              "right", _PRIORITY, data_state=data_state))
    if step.inbound:
        text = ", ".join(str(number) for number in step.inbound)
        out.append(_text(int(step.x) - fsm_layout.INBOUND_W,
                         int(step.y) + (int(step.h) - fsm_layout.TEXT_H) // 2,
                         text, _JUMP, 11, data_state=data_state))
    return "\n".join(out)


def _draw_link(link, transition_index):
    """A link polyline with its bar, arrowhead, guard text and note text.

    Every element carries ``data-transition`` with the payload-relative index
    of the transition (see ``layout_payload`` for why the index is payload-
    relative rather than link-relative).  A link that does not correspond to a
    payload transition (*transition_index* is None) emits no attribute rather
    than a wrong one.
    """
    colour = _link_colour(link)
    out = []
    points = " ".join("{0},{1}".format(int(px), int(py))
                      for px, py in link.points)
    out.append('<polyline points="{0}" fill="none" stroke="{1}" '
               'stroke-width="2"{2}/>'
               .format(points, colour,
                       _data_attrs(data_transition=transition_index)))
    if link.bar is not None:
        bx, by, orientation = link.bar
        if orientation == "h":
            out.append(_line(int(bx) - fsm_layout.BAR_HALF, by,
                             int(bx) + fsm_layout.BAR_HALF, by, colour, 3,
                             data_transition=transition_index))
        else:
            out.append(_line(bx, int(by) - _BAR_V_HALF,
                             bx, int(by) + _BAR_V_HALF, colour, 3,
                             data_transition=transition_index))
    if link.arrow is not None:
        ax, ay, direction = link.arrow
        out.append(_arrowhead(ax, ay, direction, colour,
                              data_transition=transition_index))
    if link.guard_at:
        gx, gy = link.guard_at
        out.append(_text(gx, gy, link.guard_text, _GUARD, 12,
                         data_transition=transition_index))
    if link.note_at and link.note_text:
        nx, ny = link.note_at
        out.append(_text(nx, ny, link.note_text, _JUMP, 12,
                         data_transition=transition_index))
    return "\n".join(out)


def _link_colour(link):
    if link.kind == "global":
        return _PRIORITY
    if link.kind == "jump":
        return _JUMP
    return _LINK


# ---------------------------------------------------------------------------
# small drawing primitives
# ---------------------------------------------------------------------------


def _data_attrs(data_transition=None, data_state=None):
    """The ``data-*`` attribute fragment for stable frontend selection.

    ``data-transition`` is the payload-relative index of a transition (an
    int); ``data-state`` is a full state label and is XML-escaped like every
    other source-derived string.  When neither is given the fragment is empty
    and the caller emits a plain element - a chip or the "any" box has no
    payload transition to index, so it must not carry a wrong attribute.
    """
    attrs = []
    if data_transition is not None:
        attrs.append('data-transition="{0}"'.format(int(data_transition)))
    if data_state is not None:
        attrs.append('data-state="{0}"'.format(_escape(data_state)))
    if attrs:
        return " " + " ".join(attrs)
    return ""


def _rect(x, y, w, h, fill, stroke, stroke_width,
          data_transition=None, data_state=None):
    return ('<rect x="{0}" y="{1}" width="{2}" height="{3}" fill="{4}" '
            'stroke="{5}" stroke-width="{6}"{7}/>'
            .format(int(x), int(y), int(w), int(h), fill, stroke, stroke_width,
                    _data_attrs(data_transition, data_state)))


def _line(x1, y1, x2, y2, stroke, stroke_width,
          data_transition=None, data_state=None):
    return ('<line x1="{0}" y1="{1}" x2="{2}" y2="{3}" stroke="{4}" '
            'stroke-width="{5}"{6}/>'
            .format(int(x1), int(y1), int(x2), int(y2), stroke, stroke_width,
                    _data_attrs(data_transition, data_state)))


def _text(x, y, content, fill, size, anchor="start",
          data_transition=None, data_state=None):
    """Top-anchored text.  GDI+ draws with the text top at (x, y); an SVG
    ``<text>`` y is the baseline, so shift down by roughly the cap height."""
    baseline = int(y) + size
    return ('<text x="{0}" y="{1}" font-family="Consolas, monospace" '
            'font-size="{2}" fill="{3}" text-anchor="{4}"{5}>{6}</text>'
            .format(int(x), baseline, size, fill, anchor,
                    _data_attrs(data_transition, data_state), _escape(content)))


def _centre_text(x, y, w, h, content, fill, size,
                 data_transition=None, data_state=None):
    """Text centred inside the box (x, y, w, h)."""
    return ('<text x="{0}" y="{1}" font-family="Consolas, monospace" '
            'font-size="{2}" fill="{3}" text-anchor="middle" '
            'dominant-baseline="central"{4}>{5}</text>'
            .format(int(x) + int(w) // 2, int(y) + int(h) // 2, size, fill,
                    _data_attrs(data_transition, data_state), _escape(content)))


def _arrowhead(x, y, direction, fill, data_transition=None, data_state=None):
    """Filled triangle with its TIP at (x, y), pointing *direction*."""
    x = int(x)
    y = int(y)
    if direction == "left":
        pts = [(x, y), (x + _ARROW_LEN, y - _ARROW_HALF),
               (x + _ARROW_LEN, y + _ARROW_HALF)]
    elif direction == "right":
        pts = [(x, y), (x - _ARROW_LEN, y - _ARROW_HALF),
               (x - _ARROW_LEN, y + _ARROW_HALF)]
    elif direction == "down":
        pts = [(x, y), (x - _ARROW_HALF, y - _ARROW_LEN),
               (x + _ARROW_HALF, y - _ARROW_LEN)]
    else:  # up
        pts = [(x, y), (x - _ARROW_HALF, y + _ARROW_LEN),
               (x + _ARROW_HALF, y + _ARROW_LEN)]
    points = " ".join("{0},{1}".format(px, py) for px, py in pts)
    return '<polygon points="{0}" fill="{1}"{2}/>'.format(
        points, fill, _data_attrs(data_transition, data_state))


# ---------------------------------------------------------------------------
# to_mermaid_text
# ---------------------------------------------------------------------------


def to_mermaid_text(payload, title=None):
    """Render a machine *payload* as a mermaid ``stateDiagram-v2`` block.

    Exists so callers never need to know about the ``machine_from_payload``
    adapter or the shared ``cts_shared.st.fsm_mermaid`` module.
    """
    machine = machine_from_payload(payload)
    return to_mermaid(machine, title=title)

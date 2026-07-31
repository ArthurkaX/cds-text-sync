# -*- coding: utf-8 -*-
"""
lint.py - Design checks on an authored SVG sketch, before it is compiled.

``cts visu check`` validates a *compiled* screen: bounds, member consistency,
Text-ID invariants -- the things CODESYS would reject. That is correctness, and
it runs too late to help someone still drawing.

This module checks the sketch itself, for the things that make a technically
valid screen look unfinished: coordinates off the grid, text wider than the box
holding it, a font size outside the scale, a button too small to press, a field
with nothing bound to it. None of these break the import. All of them are
visible.

Every finding carries the element index, so ``--fix`` can rewrite exactly the
attributes it flagged -- by splicing the affected start-tags back at their own
character offsets, leaving comments and formatting untouched.
"""

from __future__ import print_function

import re

from . import svg_import as _svg_import

# Coordinates and sizes snap to this. Four, not eight: eight is the *layout*
# rhythm a good sketch follows, but flagging every 4px offset as an error would
# bury the real problems.
GRID = 4

# The type scale from stylesheet.css. A size outside it means someone typed a
# number instead of picking a class.
FONT_SCALE = (11, 12, 16, 22, 28)

# Smallest comfortable hit target for a native control, in px.
MIN_BUTTON_HEIGHT = 32
MIN_BUTTON_WIDTH = 48
MIN_LAMP = 16

# Keep this far away from the canvas edge.
EDGE_MARGIN = 8

# A gap this small reads as a misalignment rather than as spacing.
CROWD_GAP = 8

_SEVERITIES = ("error", "warn", "info")


class Finding(object):
    """One lint result: what, where, and (when mechanical) how to fix it."""

    def __init__(self, rule, severity, index, message, fixes=None):
        self.rule = rule
        self.severity = severity
        self.index = index
        self.message = message
        # {attribute_name: corrected_value} -- only for mechanically fixable rules.
        self.fixes = fixes or {}

    @property
    def fixable(self):
        return bool(self.fixes)

    def __repr__(self):
        return "<Finding {0} #{1} {2}>".format(self.rule, self.index, self.message)


def _snap(value, grid=GRID):
    return int(round(float(value) / grid) * grid)


def _nearest_scale(size):
    return min(FONT_SCALE, key=lambda s: (abs(s - size), s))


def _geom(params):
    def _i(key, default=0):
        try:
            return int(float(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    return _i("x"), _i("y"), _i("width"), _i("height")


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _contains(outer, inner):
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
#
# Each rule maps a parsed element to zero or more Findings. The SVG attribute
# names in ``fixes`` are the *source* attributes, so --fix knows what to rewrite:
# a <circle> is snapped through cx/cy/r, not through the derived x/y/width.


# ``parse_svg`` files every plain shape under the type ``rectangle`` and keeps
# what is actually drawn in ``params["shape"]``, so a <circle> and a <rect> come
# back indistinguishable by type alone. That is right for the compiler and wrong
# for a message: "rectangle #1" sends an author hunting for a rectangle they
# never wrote, and the control-tag rule below would promise a plain rectangle
# where the screen will show an ellipse.
_SHAPE_NAMES = {"ellipse": "ellipse", "rounded": "rounded rectangle"}


def _shape_of(spec):
    """Name the shape an author will see, not the parser's category for it."""
    if spec["type"] != "rectangle":
        return spec["type"]
    return _SHAPE_NAMES.get(spec["params"].get("shape"), "rectangle")


def _rule_bounds(index, spec, canvas, findings):
    x, y, w, h = _geom(spec["params"])
    cw, ch = canvas["width"], canvas["height"]
    if x < 0 or y < 0 or x + w > cw or y + h > ch:
        findings.append(
            Finding(
                "bounds", "error", index,
                "{0} at ({1},{2}) {3}x{4} extends outside the {5}x{6} canvas".format(
                    _shape_of(spec), x, y, w, h, cw, ch
                ),
            )
        )


def _rule_margin(index, spec, canvas, findings):
    x, y, w, h = _geom(spec["params"])
    cw, ch = canvas["width"], canvas["height"]
    if x < 0 or y < 0 or x + w > cw or y + h > ch:
        return  # already reported by bounds; margin advice would be noise
    close = []
    if x < EDGE_MARGIN:
        close.append("left")
    if y < EDGE_MARGIN:
        close.append("top")
    if cw - (x + w) < EDGE_MARGIN:
        close.append("right")
    if ch - (y + h) < EDGE_MARGIN:
        close.append("bottom")
    if close:
        findings.append(
            Finding(
                "margin", "info", index,
                "{0} sits within {1}px of the {2} edge".format(
                    _shape_of(spec), EDGE_MARGIN, "/".join(close)
                ),
            )
        )


def _rule_grid(index, spec, source, findings):
    """Flag off-grid geometry, using whichever attributes the source element has."""
    if source is None:
        return
    fixes = {}
    for attr in ("x", "y", "width", "height", "cx", "cy", "r", "rx", "ry",
                 "x1", "y1", "x2", "y2", "data-width", "data-height"):
        raw = source.get(attr)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if attr in ("rx", "ry") and source.tag == "rect":
            # On a <rect> these are the corner radius, not a position: 2 and 4
            # are both deliberate, and snapping would round a 2px radius down
            # to a square corner. On an <ellipse> they are real geometry, so
            # only the rect case is exempt.
            continue
        if attr in ("r", "rx", "ry"):
            # Only a <circle> r and an <ellipse> rx/ry reach here; the <rect>
            # corner radius returned above. These are size, not position, so
            # grade the diameter -- the same quantity width/height is graded on.
            # Snapping the radius itself would inflate r=6, a 12px dot already
            # on the grid, into a 16px one to fix an alignment problem it does
            # not have.
            radius = _snap(value * 2) // 2
            if radius != value:
                fixes[attr] = str(int(radius))
            continue
        if attr == "y" and spec["type"] in ("label", "textfield"):
            # An SVG <text> y is a *baseline*; the compiled box top is derived
            # from it (minus the font size, or minus half the height when
            # centred). Snapping the baseline would push the box off the grid,
            # which is the opposite of what this rule is for -- so grade the
            # compiled top and shift the baseline by the same delta.
            try:
                top = float(spec["params"].get("y", value))
            except (TypeError, ValueError):
                continue
            delta = _snap(top) - top
            if delta:
                fixes[attr] = str(int(value + delta))
            continue
        snapped = _snap(value)
        if snapped != int(value) or float(int(value)) != value:
            fixes[attr] = str(snapped)
    if fixes:
        detail = ", ".join(
            "{0}={1}->{2}".format(k, source.get(k), v) for k, v in sorted(fixes.items())
        )
        findings.append(
            Finding(
                "grid", "warn", index,
                "{0} is off the {1}px grid ({2})".format(_shape_of(spec), GRID, detail),
                fixes,
            )
        )


def _rule_font_scale(index, spec, source, findings):
    if source is None:
        return
    raw = source.get("font-size")
    if raw is None:
        return
    try:
        size = int(float(raw))
    except (TypeError, ValueError):
        return
    if size in FONT_SCALE:
        return
    target = _nearest_scale(size)
    findings.append(
        Finding(
            "font-scale", "warn", index,
            "font-size {0} is outside the type scale {1}; use a class "
            "(.caption/.label/.h2/.h1/.value) or {2}".format(
                size, "/".join(str(s) for s in FONT_SCALE), target
            ),
            {"font-size": str(target)},
        )
    )


def _rule_touch_size(index, spec, findings):
    _x, _y, w, h = _geom(spec["params"])
    kind = spec["type"]
    if kind == "button":
        if h < MIN_BUTTON_HEIGHT or w < MIN_BUTTON_WIDTH:
            findings.append(
                Finding(
                    "touch-size", "warn", index,
                    "button is {0}x{1}; minimum comfortable size is {2}x{3}".format(
                        w, h, MIN_BUTTON_WIDTH, MIN_BUTTON_HEIGHT
                    ),
                )
            )
    elif kind == "lamp" and (w < MIN_LAMP or h < MIN_LAMP):
        findings.append(
            Finding(
                "touch-size", "info", index,
                "lamp is {0}x{1}; below {2}px it reads as a dot".format(w, h, MIN_LAMP),
            )
        )


def _rule_text_overflow(index, spec, findings):
    if spec["type"] not in ("label", "textfield", "button"):
        return
    params = spec["params"]
    text = params.get("text") or ""
    if not text:
        return
    _x, _y, w, _h = _geom(params)
    try:
        size = int(float(params.get("font_size", 12)))
    except (TypeError, ValueError):
        size = 12
    needed = _svg_import._estimate_text_width(text, size)
    if w and needed > w:
        findings.append(
            Finding(
                "text-overflow", "warn", index,
                '{0} text "{1}" needs about {2}px but the box is {3}px'.format(
                    spec["type"], text, needed, w
                ),
            )
        )


def _rule_anchor_box(index, spec, source, findings):
    """Anchored text needs an explicit box, or it lands nowhere in particular.

    Left-aligned text grows rightwards from x, so an estimated width costs only
    a little slack at the far end. Centre and right alignment place the glyphs
    *relative to that width*, so the same estimate moves the text itself -- and
    an author comparing sketch against preview finds it sitting somewhere they
    did not put it, with nothing in the file to explain why.
    """
    if source is None or spec["type"] not in ("label", "textfield"):
        return
    anchor = source.get("text-anchor")
    if anchor is None:
        return
    if anchor not in ("start", "middle", "end"):
        findings.append(
            Finding(
                "text-anchor", "warn", index,
                'text-anchor="{0}" is not supported and was read as "start"; '
                "use start, middle or end".format(anchor),
            )
        )
        return
    if anchor == "start" or source.get("data-width"):
        return
    findings.append(
        Finding(
            "text-anchor", "warn", index,
            'text-anchor="{0}" without data-width: the box is sized from an '
            "estimate of the text, so the alignment lands wherever that "
            "estimate falls".format(anchor),
        )
    )


def _rule_unsized_field(index, spec, source, findings):
    """A textfield needs an explicit box: what it shows is not what it says.

    A label's width can be estimated from its own text, because that text is
    what appears. A field's content is ``%d`` in the file and ``1247`` on the
    screen, so an estimate sizes the box to the format string and the value
    then runs out of it. This is the one geometry a field cannot infer.
    """
    if source is None or spec["type"] != "textfield":
        return
    missing = [a for a in ("data-width", "data-height") if not source.get(a)]
    if not missing:
        return
    findings.append(
        Finding(
            "unsized-field", "warn", index,
            "{0} has no {1}: the box is sized from the format string, not "
            "from the value it will show".format(
                _name(spec, source), " or ".join(missing)
            ),
        )
    )


# The content ``cts visu new`` writes so the starter screen has something to
# show. Every one of these is meant to be replaced. Kept in step with the
# generator by test_visu_lint.py, which regenerates a scaffold and asserts this
# rule still fires on it.
_SCAFFOLD_TEXT = (
    "Process", "Setpoints", "ACCEPT", "REJECT", "Line speed",
    "Reject threshold", "Running", "Fault", "Start", "Stop",
)
_SCAFFOLD_VARS = (
    "VisuVars.rLineSpeed", "VisuVars.rRejectLimit", "VisuVars.xRunning",
    "VisuVars.xFault", "VisuVars.xStart", "VisuVars.xStop",
)
# Out of sixteen. A real screen may well have a Start button and a Fault lamp;
# it will not also be bound to six variables it never declared.
_SCAFFOLD_KEPT = 8


def _element_vars(params):
    yield (params.get("text_var") or "").strip()
    yield (params.get("var") or "").strip()
    for entry in params.get("configured_inputs") or []:
        yield ((entry.get("values") or {}).get("variable") or "").strip()


def _rule_scaffold(elements, findings):
    """Grade what the screen says, not only where it sits.

    Every other rule measures geometry, so a sketch that was generated and never
    edited passes all of them -- the starter screen is, after all, laid out
    correctly. It is also the one screen certain to be wrong: it shows a process
    nobody runs, bound to variables nobody declared. Ten authors were set the
    same task and one shipped the scaffold with its title changed; lint called it
    OK and had, by its own rules, no reason not to.
    """
    kept = 0
    first = None
    for index, spec in enumerate(elements):
        params = spec["params"]
        hits = 0
        if (params.get("text") or "").strip() in _SCAFFOLD_TEXT:
            hits += 1
        hits += sum(1 for v in _element_vars(params) if v in _SCAFFOLD_VARS)
        if hits and first is None:
            first = index
        kept += hits
    if kept < _SCAFFOLD_KEPT:
        return
    findings.append(
        Finding(
            # Info, not warn: the scaffold is not *wrong*, it is unfinished, and
            # the first thing an author sees should not be a complaint about
            # code they did not write. It only has to stop lint from answering
            # "no design problems found" to a screen that says nothing yet.
            "scaffold", "info", first or 0,
            "{0} of the starter screen's placeholders are still here: replace "
            "the placeholder text and variable bindings with your own"
            .format(kept),
        )
    )


def _rule_empty_panel(elements, sources, findings):
    """A panel with nothing inside it is a hole, not a layout.

    This rule exists to pull against the rest of the file. Overlap and crowding
    both reward taking things out, and an author with findings to clear will do
    exactly that -- one deleted every annotation from a P&ID to reach a clean
    report. Emptiness has to cost something too, or the cheapest way to satisfy
    the linter is to draw nothing.
    """
    boxes = []
    for index, spec in enumerate(elements):
        source = sources[index] if index < len(sources) else None
        boxes.append((index, spec, source, _geom(spec["params"])))
    for index, spec, source, geom in boxes:
        if source is None:
            continue
        if "panel" not in (source.get("class") or "").split():
            continue
        if any(other != index and _contains(geom, g) for other, _s, _c, g in boxes):
            continue
        x, y = _source_xy(spec, source)
        findings.append(
            Finding(
                "empty-panel", "warn", index,
                "panel at {0},{1} has nothing in it".format(x, y),
            )
        )


def _luma(hex_color):
    """Rough perceived brightness of ``#RRGGBB``, 0..255. ``None`` if unparsable."""
    text = (hex_color or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return 0.299 * r + 0.587 * g + 0.114 * b


def _rule_lonely_card(elements, sources, theme, findings):
    """A ``card`` is an inner surface; on the screen itself it is invisible.

    ``panel`` and ``card`` are one step apart, which means a card lands close to
    the screen background -- in the light palette #EDEFF2 on #F4F5F7, under 3%
    apart. Inside a panel that step is the whole point; sitting straight on the
    background it draws nothing an author can see, and the report that came back
    was "panel and card are the same colour" from someone looking at a screen
    where one of the two boxes had simply vanished.

    Checked against the resolved palette rather than assumed, so a project style
    that does separate the two -- the dark scheme does -- never sees this.
    """
    card = _luma((theme or {}).get("card"))
    screen = _luma((theme or {}).get("screen"))
    if card is None or screen is None or abs(card - screen) >= 12:
        return
    boxes = []
    for index, spec in enumerate(elements):
        source = sources[index] if index < len(sources) else None
        boxes.append((index, spec, source, _geom(spec["params"])))
    for index, spec, source, geom in boxes:
        if source is None:
            continue
        if "card" not in (source.get("class") or "").split():
            continue
        if any(other != index and _contains(g, geom) for other, _s, _c, g in boxes):
            continue
        x, y = _source_xy(spec, source)
        findings.append(
            Finding(
                "lonely-card", "warn", index,
                "card at {0},{1} sits on the screen background, where it is "
                "almost invisible; a top-level box is class=\"panel\"".format(x, y),
            )
        )


def _rule_unbound_field(index, spec, findings):
    if spec["type"] != "textfield":
        return
    if not (spec["params"].get("text_var") or "").strip():
        findings.append(
            Finding(
                "unbound-field", "warn", index,
                "textfield has no data-text-var; it will show static text only",
            )
        )


# Words that name a machine state rather than a thing.
_STATE_WORDS = frozenset("""
    stopped running started starting stopping active inactive idle ready
    fault faulted ok error alarm alarming on off open closed opened
    enabled disabled online offline normal warning manual auto automatic
    true false yes no empty full busy done failed passed complete
    connected disconnected present absent armed disarmed tripped healthy
""".split())

# "=", ":", or a dash with space on both sides. A bare hyphen is not a
# separator: "E-Stop" is one word, and splitting on it would make every
# hyphenated name a candidate.
_SEPARATOR_RE = re.compile(u"=|:|\\s[-–—]\\s")


def _asserted_state(text):
    """The state a caption claims, or ``None`` if it is only labelling.

    Split on the separator rather than searching for a state word anywhere in
    the string. "Running" on its own is the legend beside a lamp, and "Motor
    Running" is that same legend with the machine named -- both are correct,
    and a rule matching the word alone would fire on every well-labelled
    screen. What is wrong is a caption that *joins* a name to a state, because
    then the right-hand side is a reading.
    """
    parts = _SEPARATOR_RE.split(text)
    if len(parts) < 2:
        return None
    head, tail = parts[0].strip(), parts[-1].strip()
    if not head or not tail:
        return None  # "Line speed:" is a label waiting for its field
    if tail.split()[-1].strip(".,;!").lower() in _STATE_WORDS:
        return tail
    return None


def _rule_static_state(index, spec, source, findings):
    """A caption reporting a state it is not bound to, and never will be.

    Three screens in a row came back with one: a red "E-Stop = Stopped" button
    and a header reading "9 sensors -- diagnostics active". Both are plain text
    compiled into a Text ID, so they say the same thing whether the machine is
    stopped or running -- and, being the most declarative thing on the screen,
    they are what an operator reads as instrumentation. Every geometry rule
    passes them, which is exactly the problem: the screen looks finished.
    """
    if spec["type"] not in ("label", "textfield", "button"):
        return
    params = spec["params"]
    if (params.get("text_var") or "").strip():
        return  # bound: the text is a format string, not a claim
    claim = _asserted_state((params.get("text") or "").strip())
    if claim is None:
        return
    findings.append(
        Finding(
            "static-state", "warn", index,
            '{0} reports "{1}" as static text: it is compiled into a Text ID '
            "and will read the same whether or not that is true. Bind it -- a "
            "textfield with data-text-var, or a lamp with data-var".format(
                _name(spec, source), claim
            ),
        )
    )


def _rule_button_contract(index, spec, source, findings):
    """A button needs a caption and something to do -- both are easy to omit.

    SVG has no text content for a ``<rect>``, so
    ``<rect data-cds-type="button">Start</rect>`` compiles to a blank button
    with no error anywhere. The caption comes from ``data-text``, the behaviour
    from ``data-cds-tap`` / ``data-cds-action``.
    """
    if spec["type"] != "button":
        return
    params = spec["params"]
    if not (params.get("text") or "").strip() and not (params.get("text_id") or "").strip():
        findings.append(
            Finding(
                "empty-button", "warn", index,
                '{0} has no caption; set data-text="..." '
                "(a <rect> cannot carry text content)".format(
                    _name(spec, source)
                ),
            )
        )
    if not (
        params.get("tap_var")
        or params.get("configured_inputs")
        or params.get("input_actions")
    ):
        # warn, not info: a captioned button that does nothing is worse than a
        # blank one, because the operator has no way to tell. The caption is in
        # the message for the same reason -- a screen with five buttons made
        # "button #32" a tag-counting exercise.
        findings.append(
            Finding(
                "inert-button", "warn", index,
                '{0} does nothing when pressed; add data-cds-tap="Var" or '
                'data-cds-action="..."'.format(_name(spec, source)),
            )
        )


# Which SVG tag each data-cds-type is promoted from. parse_svg matches on the
# pair, so a control attribute on any other tag is not an error -- it simply
# never matches, and the element falls through to the plain shape parser with
# data-var, data-text and the rest dropped on the floor.
_CONTROL_TAGS = {
    "button": "rect",
    "lamp": "rect",
    "image-switcher": "rect",
    "combobox": "rect",
    "alarm-banner": "rect",
    "frame": "rect",
    "textfield": "text",
}


def _rule_control_tag(index, spec, source, findings):
    """A control attribute on the wrong tag compiles to a dead decoration.

    ``<circle data-cds-type="lamp">`` is the one that bites: a circle is the
    natural shape for an indicator light, and nothing about the result says
    otherwise -- it draws, it lints clean, and it silently has no variable bound
    to it, so it sits at one colour forever. The same goes for any control on a
    tag it is not promoted from. Warn rather than error: the sketch is still
    valid SVG and still compiles, it just does not do what it says.
    """
    if source is None:
        return
    kind = (source.get("data-cds-type") or "").strip().lower()
    if not kind:
        return
    wanted = _CONTROL_TAGS.get(kind)
    if wanted is None:
        findings.append(
            Finding(
                "control-tag", "warn", index,
                'unknown data-cds-type="{0}"; it will be ignored and the element '
                "drawn as a plain {1}".format(kind, _shape_of(spec)),
            )
        )
    elif source.tag != wanted:
        findings.append(
            Finding(
                "control-tag", "warn", index,
                'data-cds-type="{0}" only works on <{1}>, not <{2}>: this is being '
                "drawn as a plain {3} with its bindings dropped".format(
                    kind, wanted, source.tag, _shape_of(spec)
                ),
            )
        )


def _rule_inert_class(index, spec, source, findings):
    """A colour class on a native control does nothing, and says it does.

    Buttons, textfields and lamps take the CODESYS control style; the class
    system does not reach them. Writing ``class="value"`` on a field is not an
    error and not a no-op the author can see -- it changes neither the size nor
    the colour, so the screen comes back looking like the class was wrong rather
    than ignored. Info, because the sketch is otherwise fine.
    """
    if source is None or spec["type"] not in ("button", "textfield", "lamp"):
        return
    cls = (source.get("class") or "").strip()
    if cls:
        findings.append(
            Finding(
                "inert-class", "info", index,
                'class="{0}" has no effect on a {1}: it takes the native CODESYS '
                "control style. Set font-size directly if you meant the size."
                .format(cls, spec["type"]),
            )
        )


def _rule_unbound_lamp(index, spec, findings):
    if spec["type"] != "lamp":
        return
    if not (spec["params"].get("var") or "").strip():
        findings.append(
            Finding(
                "unbound-lamp", "info", index,
                'lamp has no data-var; it will stay in its off state',
            )
        )


# Overlapping plain shapes is how a P&ID is drawn -- a pipe run *should* meet
# the pump it feeds. Overlap only becomes a defect when it can hide a caption or
# block a control, so severity depends on what is involved.
_DECORATIVE = ("rectangle", "line")

# Half the 16px padding the skill documents. Reporting anything under 16 would
# fire on every deliberately tight layout; the point of this bar is to catch
# content that reads as clipped, not content that is merely close.
_MIN_PADDING = 8


# The P&ID section of stylesheet.css. Shapes wearing these classes are drawing a
# process, not laying out a page, and the two sets of habits disagree about what
# a small gap means.
_PID_CLASSES = ("pipe-water", "metal")


def _is_pid(source):
    if source is None:
        return False
    return any(c in _PID_CLASSES for c in (source.get("class") or "").split())


def _is_type(source):
    """True for a ``<text>`` -- an element whose box the author never typed.

    A ``<rect>`` carries its width and height in the file, so the gap next to it
    is a number someone chose. A ``<text>`` carries a baseline and a font: the
    box comes from ``_estimate_text_height`` and a table of glyph advances, and
    the space it leaves is descender room rather than a margin. Measuring
    between two of those measures our own estimate.
    """
    return source is not None and source.tag == "text"


def _source_xy(spec, source):
    """The coordinates the author actually typed.

    Prefer the source attributes over the compiled box: a ``<text>`` y is a
    baseline and the box top is derived from it, so reporting the derived value
    would point at a number that appears nowhere in the sketch.
    """
    if source is not None:
        for xkey, ykey in (("x", "y"), ("cx", "cy"), ("x1", "y1")):
            xval, yval = source.get(xkey), source.get(ykey)
            if xval is not None and yval is not None:
                return xval, yval
    x, y, _w, _h = _geom(spec["params"])
    return str(x), str(y)


def _name(spec, source):
    """Name an element the way an author can find it in the file.

    A finding that reads only "label #16" cannot be matched back to a line of
    the sketch without counting tags by hand, which is the one thing an author
    has no tool for -- so a finding states where the element sits and what it
    says.
    """
    x, y = _source_xy(spec, source)
    text = (spec["params"].get("text") or "").strip()
    if text:
        if len(text) > 20:
            text = text[:17] + "..."
        return '{0} "{1}" at {2},{3}'.format(_shape_of(spec), text, x, y)
    return "{0} at {1},{2}".format(_shape_of(spec), x, y)


def _describe(index, spec, source):
    """:func:`_name` plus the element index, for findings that name a *pair*.

    The reporter already prints the index of the element a finding is filed
    against, so only the other half of a pair needs one spelled out -- but a
    message that numbered one of two elements and not the other would read as
    though they were different kinds of thing.
    """
    name = _name(spec, source)
    shape = _shape_of(spec)
    return "{0} #{1}{2}".format(shape, index, name[len(shape):])


def _pair_boxes(elements, sources):
    boxes = []
    for i, spec in enumerate(elements):
        if spec["type"] == "line":
            continue
        source = sources[i] if i < len(sources) else None
        boxes.append((i, spec, source, _geom(spec["params"])))
    return boxes


def _starts_inside(outer, oshape, inner, ishape):
    """True when content *inner* begins within container *outer*.

    ``_contains`` already excuses proper nesting, so what reaches here is a
    partial overlap, and there are two very different ones. Two labels that
    drifted into each other is a collision -- neither is inside the other, they
    are simply in the same place. A caption whose box starts inside the card and
    ends past its edge is an *overflow*: the author sized the parent and let the
    child grow, and "the card overlaps the label" sends them looking for the
    wrong mistake.

    A plain shape is the only thing that acts as a container here, so the
    distinction is drawn on type rather than on which box happens to be bigger:
    a 100px-tall field inside a 72px card has the *larger* area and is still the
    thing that overflowed.
    """
    if oshape["type"] != "rectangle" or ishape["type"] == "rectangle":
        return False
    ox, oy, ow, oh = outer
    ix, iy, _iw, _ih = inner
    return ox <= ix <= ox + ow and oy <= iy <= oy + oh


def _rule_overlap(elements, sources, findings):
    boxes = _pair_boxes(elements, sources)
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ia, sa, ca, ga = boxes[a]
            ib, sb, cb, gb = boxes[b]
            if _contains(ga, gb) or _contains(gb, ga):
                continue  # nesting is how panels and their contents are built
            if not _overlaps(ga, gb):
                continue
            decorative = sa["type"] in _DECORATIVE and sb["type"] in _DECORATIVE
            severity = "info" if decorative else "warn"
            if _starts_inside(ga, sa, gb, sb):
                # File it against the child: it is the one whose size is wrong.
                findings.append(
                    Finding(
                        "overflow", severity, ib,
                        "{0} overflows {1}".format(
                            _describe(ib, sb, cb), _describe(ia, sa, ca)
                        ),
                    )
                )
                continue
            if _starts_inside(gb, sb, ga, sa):
                findings.append(
                    Finding(
                        "overflow", severity, ia,
                        "{0} overflows {1}".format(
                            _describe(ia, sa, ca), _describe(ib, sb, cb)
                        ),
                    )
                )
                continue
            findings.append(
                Finding(
                    "overlap", severity, ia,
                    "{0} overlaps {1}".format(
                        _describe(ia, sa, ca), _describe(ib, sb, cb)
                    ),
                )
            )


def _rule_container_padding(elements, sources, findings):
    """Content flush against the edge of the panel or card holding it.

    The skill asks for 16px of padding inside a panel and grades the screen on
    it, and nothing measured it: a field whose box ended exactly on its card's
    bottom edge, and a row of lamps sitting on the panel border, both came back
    "Sketch OK". Neither is an overlap -- the child is properly inside its
    parent, which is why every other rule passes it -- and both render as
    content that looks clipped by the box around it.

    Only content is measured. A plain rectangle flush inside a card is the
    accent bar ``cts visu new`` writes itself, and a line flush across a panel
    is a divider; those are drawn to touch. The bar is half the documented
    padding, so a tight-but-deliberate 8px layout is left alone and only flush
    or nearly-flush content is reported.

    Measured against the *innermost* container holding the content. A card
    inside a panel means two boxes have the same bottom edge, and naming both
    of them for one field reads as two problems where the author has one.
    """
    containers = []
    for _index, spec, source, geom in _pair_boxes(elements, sources):
        if source is None or spec["type"] not in _DECORATIVE:
            continue
        classes = (source.get("class") or "").split()
        if "panel" not in classes and "card" not in classes:
            continue
        containers.append(("panel" if "panel" in classes else "card", geom))
    if not containers:
        return
    for child_index, child, child_source, child_geom in _pair_boxes(
        elements, sources
    ):
        if child["type"] in _DECORATIVE:
            continue
        holding = [
            (kind, geom) for kind, geom in containers if _contains(geom, child_geom)
        ]
        if not holding:
            continue
        kind, (ox, oy, ow, oh) = min(holding, key=lambda pair: pair[1][2] * pair[1][3])
        cx, cy, cw, ch = child_geom
        gaps = (
            ("left", cx - ox),
            ("top", cy - oy),
            ("right", (ox + ow) - (cx + cw)),
            ("bottom", (oy + oh) - (cy + ch)),
        )
        tight = [(side, gap) for side, gap in gaps if gap < _MIN_PADDING]
        if not tight:
            continue
        side, gap = min(tight, key=lambda pair: pair[1])
        findings.append(
            Finding(
                "padding", "warn", child_index,
                "{0} is {1}px from the {2} edge of the {3} at {4},{5}; "
                "keep 16px inside a container".format(
                    _describe(child_index, child, child_source),
                    gap, side, kind, ox, oy,
                ),
            )
        )


def _rule_crowding(elements, sources, findings):
    """A 1-7px gap is neither alignment nor spacing -- it is a slip.

    Unless both shapes are drawing a P&ID: two pipe segments that butt against
    the equipment between them are a process drawn correctly, not a near-miss,
    and flagging them taught more than one author to pull the drawing apart
    until it stopped looking like a P&ID at all.

    And unless both are type. The skill sets a label's baseline 24px above its
    field's, which for a 12px label over a 16px value leaves exactly 4px between
    the two boxes -- so following the documented rhythm produced the finding,
    and the only way to silence it was to stop following it. That gap is not a
    slip either: nobody typed it, it is descender space under an estimated box,
    and the pair reads as one item precisely because it is tight. Type that
    really does collide is still an ``overlap``, and type off the rhythm is
    still a ``grid`` finding. Page furniture -- two cards, a card and its
    caption -- keeps the rule, because there the gap really is a slip.
    """
    boxes = _pair_boxes(elements, sources)
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ia, sa, ca, (ax, ay, aw, ah) = boxes[a]
            ib, sb, cb, (bx, by, bw, bh) = boxes[b]
            if _is_pid(ca) and _is_pid(cb):
                continue
            if _is_type(ca) and _is_type(cb):
                continue
            # Horizontal neighbours: overlapping vertical spans, small x gap.
            if not (ay + ah <= by or by + bh <= ay):
                gap = bx - (ax + aw) if bx >= ax else ax - (bx + bw)
                if 0 < gap < CROWD_GAP:
                    findings.append(
                        Finding("crowding", "info", ia,
                                "{0} and {1} are {2}px apart horizontally".format(
                                    _describe(ia, sa, ca),
                                    _describe(ib, sb, cb), gap)))
                    continue
            if not (ax + aw <= bx or bx + bw <= ax):
                gap = by - (ay + ah) if by >= ay else ay - (by + bh)
                if 0 < gap < CROWD_GAP:
                    findings.append(
                        Finding("crowding", "info", ia,
                                "{0} and {1} are {2}px apart vertically".format(
                                    _describe(ia, sa, ca),
                                    _describe(ib, sb, cb), gap)))


# ---------------------------------------------------------------------------
# Source start-tag index (for --fix)
# ---------------------------------------------------------------------------

_DEFS_RE = re.compile(r"<defs\b.*?</defs\s*>", re.DOTALL | re.IGNORECASE)
# Comments have to be masked for the same reason <defs> is: parse_svg does not
# see them, so anything in here that *looks* like a start tag would add an entry
# to the index that has no element behind it -- and every finding after that
# point would then be attributed to its neighbour, with --fix rewriting the
# wrong element's attributes. Sketches explain themselves in comments, and a
# comment about a tag naturally names the tag ("a pipe is a rect, not a
# <line>"), so this is reached by writing an ordinary remark.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<(rect|circle|ellipse|line|text)\b[^>]*?/?>", re.IGNORECASE)
_ATTR_RE_CACHE = {}


def _attr_re(name):
    """Regex matching one attribute assignment inside a start-tag."""
    if name not in _ATTR_RE_CACHE:
        _ATTR_RE_CACHE[name] = re.compile(
            r'(\b{0}\s*=\s*")([^"]*)(")'.format(re.escape(name))
        )
    return _ATTR_RE_CACHE[name]


def index_source_tags(svg_text):
    """Return the start-tag spans of top-level drawable elements, in order.

    The order matches ``parse_svg``'s element list because both walk the
    document once and both skip ``<defs>`` and comments. Returns
    ``[(start, end, tag_text)]``.
    """
    masked = _DEFS_RE.sub(lambda m: " " * len(m.group(0)), svg_text)
    masked = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), masked)
    return [(m.start(), m.end(), m.group(0)) for m in _TAG_RE.finditer(masked)]


class _SourceElement(object):
    """Read-only attribute view over one start-tag, for the source-aware rules.

    ``tag`` is the element name in lowercase. Rules need it because the same
    attribute means different things on different elements -- ``rx`` is a corner
    radius on a ``<rect>`` and a semi-axis on an ``<ellipse>``.
    """

    def __init__(self, tag_text):
        name = re.match(r"<\s*([A-Za-z_][-A-Za-z0-9_:.]*)", tag_text)
        self.tag = name.group(1).lower() if name else ""
        self._attrs = dict(
            (m.group(1), m.group(3))
            for m in re.finditer(r'([A-Za-z_][-A-Za-z0-9_:.]*)\s*=\s*(")([^"]*)"', tag_text)
        )

    def get(self, name, default=None):
        return self._attrs.get(name, default)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lint_svg(svg_text, theme=None, project_dir=None, background=None, scheme=None):
    """Parse and check an SVG sketch. Returns ``(findings, parsed)``.

    Raises whatever ``parse_svg`` raises -- a sketch that will not parse has a
    correctness problem, and reporting design nits on top of that would only
    bury it.

    ``scheme`` is passed straight through: ``None`` means "whatever the sketch
    says", so linting sees exactly the palette the compile step will use.
    """
    parsed = _svg_import.parse_svg(
        svg_text,
        theme=theme,
        project_dir=project_dir,
        background=background,
        scheme=scheme,
    )
    elements = parsed["elements"]
    canvas = parsed["canvas"]

    tags = index_source_tags(svg_text)
    sources = [_SourceElement(t[2]) for t in tags]

    findings = []
    for index, spec in enumerate(elements):
        source = sources[index] if index < len(sources) else None
        _rule_bounds(index, spec, canvas, findings)
        _rule_margin(index, spec, canvas, findings)
        _rule_grid(index, spec, source, findings)
        _rule_font_scale(index, spec, source, findings)
        _rule_touch_size(index, spec, findings)
        _rule_text_overflow(index, spec, findings)
        _rule_anchor_box(index, spec, source, findings)
        _rule_unsized_field(index, spec, source, findings)
        _rule_unbound_field(index, spec, findings)
        _rule_static_state(index, spec, source, findings)
        _rule_button_contract(index, spec, source, findings)
        _rule_unbound_lamp(index, spec, findings)
        _rule_control_tag(index, spec, source, findings)
        _rule_inert_class(index, spec, source, findings)
    _rule_overlap(elements, sources, findings)
    _rule_crowding(elements, sources, findings)
    _rule_container_padding(elements, sources, findings)
    _rule_scaffold(elements, findings)
    _rule_empty_panel(elements, sources, findings)
    _rule_lonely_card(elements, sources, parsed.get("theme"), findings)

    order = dict((s, i) for i, s in enumerate(_SEVERITIES))
    findings.sort(key=lambda f: (order.get(f.severity, 9), f.index, f.rule))
    return findings, parsed


def apply_fixes(svg_text, findings):
    """Rewrite the mechanically fixable findings. Returns ``(new_text, count)``.

    Only the flagged start-tags are touched, spliced back at their own offsets,
    so comments, whitespace and every other byte of the sketch survive intact.
    Refuses to return a changed document whose element count no longer matches.
    """
    tags = index_source_tags(svg_text)
    by_index = {}
    for finding in findings:
        if finding.fixable and 0 <= finding.index < len(tags):
            by_index.setdefault(finding.index, {}).update(finding.fixes)
    if not by_index:
        return svg_text, 0

    out = []
    cursor = 0
    changed = 0
    for index, (start, end, tag_text) in enumerate(tags):
        fixes = by_index.get(index)
        if not fixes:
            continue
        new_tag = tag_text
        for attr, value in fixes.items():
            new_tag, n = _attr_re(attr).subn(
                lambda m, v=value: m.group(1) + v + m.group(3), new_tag, count=1
            )
            if n:
                changed += 1
        out.append(svg_text[cursor:start])
        out.append(new_tag)
        cursor = end
    out.append(svg_text[cursor:])
    result = "".join(out)

    if len(index_source_tags(result)) != len(tags):
        raise ValueError(
            "internal: fix pass changed the element count; sketch left untouched"
        )
    return result, changed

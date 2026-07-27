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


def _rule_bounds(index, spec, canvas, findings):
    x, y, w, h = _geom(spec["params"])
    cw, ch = canvas["width"], canvas["height"]
    if x < 0 or y < 0 or x + w > cw or y + h > ch:
        findings.append(
            Finding(
                "bounds", "error", index,
                "{0} at ({1},{2}) {3}x{4} extends outside the {5}x{6} canvas".format(
                    spec["type"], x, y, w, h, cw, ch
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
                    spec["type"], EDGE_MARGIN, "/".join(close)
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
                "{0} is off the {1}px grid ({2})".format(spec["type"], GRID, detail),
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


def _rule_button_contract(index, spec, findings):
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
                'button has no caption; set data-text="..." '
                "(a <rect> cannot carry text content)",
            )
        )
    if not (
        params.get("tap_var")
        or params.get("configured_inputs")
        or params.get("input_actions")
    ):
        findings.append(
            Finding(
                "inert-button", "info", index,
                'button does nothing when pressed; add data-cds-tap="Var" or '
                'data-cds-action="..."',
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


def _rule_overlap(elements, findings):
    boxes = []
    for i, spec in enumerate(elements):
        if spec["type"] == "line":
            continue
        boxes.append((i, spec["type"], _geom(spec["params"])))
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ia, ta, ga = boxes[a]
            ib, tb, gb = boxes[b]
            if _contains(ga, gb) or _contains(gb, ga):
                continue  # nesting is how panels and their contents are built
            if not _overlaps(ga, gb):
                continue
            decorative = ta in _DECORATIVE and tb in _DECORATIVE
            findings.append(
                Finding(
                    "overlap", "info" if decorative else "warn", ia,
                    "{0} #{1} overlaps {2} #{3}".format(ta, ia, tb, ib),
                )
            )


def _rule_crowding(elements, findings):
    """A 1-7px gap is neither alignment nor spacing -- it is a slip."""
    boxes = []
    for i, spec in enumerate(elements):
        if spec["type"] == "line":
            continue
        boxes.append((i, spec["type"], _geom(spec["params"])))
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ia, ta, (ax, ay, aw, ah) = boxes[a]
            ib, tb, (bx, by, bw, bh) = boxes[b]
            # Horizontal neighbours: overlapping vertical spans, small x gap.
            if not (ay + ah <= by or by + bh <= ay):
                gap = bx - (ax + aw) if bx >= ax else ax - (bx + bw)
                if 0 < gap < CROWD_GAP:
                    findings.append(
                        Finding("crowding", "info", ia,
                                "{0} #{1} and {2} #{3} are {4}px apart "
                                "horizontally".format(ta, ia, tb, ib, gap)))
                    continue
            if not (ax + aw <= bx or bx + bw <= ax):
                gap = by - (ay + ah) if by >= ay else ay - (by + bh)
                if 0 < gap < CROWD_GAP:
                    findings.append(
                        Finding("crowding", "info", ia,
                                "{0} #{1} and {2} #{3} are {4}px apart "
                                "vertically".format(ta, ia, tb, ib, gap)))


# ---------------------------------------------------------------------------
# Source start-tag index (for --fix)
# ---------------------------------------------------------------------------

_DEFS_RE = re.compile(r"<defs\b.*?</defs\s*>", re.DOTALL | re.IGNORECASE)
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
    document once and both skip ``<defs>``. Returns ``[(start, end, tag_text)]``.
    """
    masked = _DEFS_RE.sub(lambda m: " " * len(m.group(0)), svg_text)
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
        _rule_unbound_field(index, spec, findings)
        _rule_button_contract(index, spec, findings)
        _rule_unbound_lamp(index, spec, findings)
    _rule_overlap(elements, findings)
    _rule_crowding(elements, findings)

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

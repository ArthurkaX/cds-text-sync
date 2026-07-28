# -*- coding: utf-8 -*-
"""
commands.py - cts visu command implementations (offline).

These functions are thin: they resolve the target screen file, call the
builder/catalog engine, write the result into project-view, and print a result.
They never touch the daemon or import.
"""

from __future__ import print_function

import os
import sys

from . import builder, svg_export, svg_import, themes
from . import catalog as _catalog


def _err(msg):
    print("[ERROR] {0}".format(msg), file=sys.stderr)


def _ok(msg):
    print("[OK] {0}".format(msg), file=sys.stderr)


def _warn(msg):
    print("[WARN] {0}".format(msg), file=sys.stderr)


# How many times ``lint --fix`` re-runs itself before giving up. Fixes feed each
# other -- a new font size moves the box top the grid rule grades -- so one pass
# leaves work behind; a handful reaches a fixed point on any sketch that has one.
_FIX_PASSES = 5


def _folder_to_dir(project_view_dir, folder):
    """Map a CODESYS folder path (e.g. 'Runtime/PLC Logic/...') to a real dir."""
    folder = (folder or "").replace("\\", "/").strip("/")
    if not folder:
        return project_view_dir
    return os.path.join(project_view_dir, *folder.split("/"))


def _resolve_screen_path(project_view_dir, screen, folder):
    """Resolve --screen (name or path) to an absolute .xml path.

    If ``screen`` is an existing path, use it. Otherwise treat it as a name
    under ``folder`` (relative to project-view). When ``folder`` is omitted or
    the name is not found there, fall back to a recursive search of
    project-view for ``<name>.xml`` (so callers need not repeat --folder).
    """
    if not (screen or "").strip():
        # Falling through with an empty name builds "<project-view>/.xml" and
        # reports it as a missing screen, which reads as "the file I asked for
        # is gone" rather than "you did not ask for one".
        _err(
            "No screen given: pass --screen <name> to target an existing "
            "screen, or --create-screen --name <name> to make a new one"
        )
        sys.exit(1)
    if os.path.isabs(screen) and os.path.isfile(screen):
        return screen
    if os.path.isfile(screen):
        return os.path.abspath(screen)
    name = screen if screen.endswith(".xml") else screen + ".xml"
    target_dir = _folder_to_dir(project_view_dir, folder)
    candidate = os.path.join(target_dir, name)
    if os.path.isfile(candidate):
        return candidate
    # Recursive fallback: find <name>.xml anywhere under project-view.
    matches = []
    for dirpath, _dirs, files in os.walk(project_view_dir):
        if name in files:
            matches.append(os.path.join(dirpath, name))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        _err(
            "Screen name '{0}' is ambiguous ({1} matches); pass --folder to "
            "disambiguate:\n  {2}".format(screen, len(matches), "\n  ".join(matches))
        )
        sys.exit(1)
    return candidate


# ---------------------------------------------------------------------------
# create-screen
# ---------------------------------------------------------------------------


def create_screen(project_view_dir, name, folder, width, height, start_visu):
    target_dir = _folder_to_dir(project_view_dir, folder)
    if not os.path.isdir(target_dir):
        _err(
            "Target folder does not exist: {0}\n"
            "Point --folder at an existing project-view folder.".format(target_dir)
        )
        sys.exit(1)

    sibling = builder.find_sibling_object(target_dir)
    if sibling is None:
        _err(
            "Folder '{0}' contains no existing object to copy placement from.\n"
            "Placement (ParentGuid/ParentSVNodeGuid) is derived from a sibling "
            "object. Choose a folder that already contains at least one object.".format(
                folder
            )
        )
        sys.exit(1)

    placement = builder.read_placement_from_sibling(sibling)
    out_path = os.path.join(target_dir, name + ".xml")
    if os.path.exists(out_path):
        _err("Screen already exists: {0}".format(out_path))
        sys.exit(1)

    xml_text = builder.build_screen(
        name=name,
        size_x=width,
        size_y=height,
        parent_guid=placement["parent_guid"],
        parent_svnode_guid=placement["parent_svnode_guid"],
        path_segments=placement["path"],
        is_start_visu=start_visu,
    )
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)
    _ok("Created screen {0} ({1}x{2}) at {3}".format(name, width, height, out_path))
    print(out_path)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def add_element(project_view_dir, screen, folder, type_name, params):
    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)
    try:
        catalog = _catalog.load_catalog(type_name)
    except _catalog.CatalogError as exc:
        _err(str(exc))
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()
    try:
        new_xml, geometry, info = builder.append_element(xml_text, catalog, params)
    except builder.BuilderError as exc:
        _err(str(exc))
        sys.exit(1)

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(new_xml)
    _ok(
        "Added {0} '{1}' at X={2} Y={3} W={4} H={5} (Center {6},{7})".format(
            info["type"],
            info["identifier"],
            geometry["x"],
            geometry["y"],
            geometry["width"],
            geometry["height"],
            geometry["center_x"],
            geometry["center_y"],
        )
    )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def list_screen(project_view_dir, screen, folder):
    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()
    elements = builder.list_elements(xml_text)
    if not elements:
        print("(no elements)")
        return
    print(
        "{0:<3} {1:<16} {2:<16} {3:>6} {4:>6} {5:>6} {6:>6}".format(
            "Idx", "Type", "Identifier", "X", "Y", "W", "H"
        )
    )
    for el in elements:
        print(
            "{0:<3} {1:<16} {2:<16} {3:>6} {4:>6} {5:>6} {6:>6}".format(
                el["index"],
                el["type"],
                el["identifier"],
                el.get("x") or "-",
                el.get("y") or "-",
                el.get("width") or "-",
                el.get("height") or "-",
            )
        )


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def check_screen(project_view_dir, screen, folder):
    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()

    size_x, size_y = builder.read_screen_size(xml_text)
    elements = builder.list_elements(xml_text)
    problems = []
    boxes = []

    for el in elements:
        members = el.get("members", {})
        try:
            x = int(el.get("x") or 0)
            y = int(el.get("y") or 0)
            w = int(el.get("width") or 0)
            h = int(el.get("height") or 0)
        except ValueError:
            problems.append("{0}: non-numeric geometry".format(el["identifier"]))
            continue

        for e in builder.validate_bounds(
            {"x": x, "y": y, "width": w, "height": h}, size_x, size_y
        ):
            problems.append("{0}: {1}".format(el["identifier"], e))

        cx = members.get(550940142, {}).get("value")
        cy = members.get(1473355128, {}).get("value")
        if cx is not None and str(cx).strip() != str(x + w // 2):
            problems.append(
                "{0}: CenterX {1} != X+W/2 ({2})".format(
                    el["identifier"], cx, x + w // 2
                )
            )
        if cy is not None and str(cy).strip() != str(y + h // 2):
            problems.append(
                "{0}: CenterY {1} != Y+H/2 ({2})".format(
                    el["identifier"], cy, y + h // 2
                )
            )

        # Color CanonicalName non-empty.
        for mid, m in members.items():
            if m.get("kind") == "color" and not (m.get("canonical_name") or "").strip():
                problems.append(
                    "{0}: color member {1} has empty CanonicalName".format(
                        el["identifier"], mid
                    )
                )

        # Text / Text-ID invariant.
        text_m = members.get(390574330, {})
        if (text_m.get("value") or "").strip():
            if not (members.get(823443203, {}).get("value") or "").strip():
                problems.append(
                    "{0}: has non-empty text but no Text ID (823443203); "
                    "CODESYS will reject the import".format(el["identifier"])
                )

        boxes.append((el["identifier"], el.get("type") or "", x, y, w, h))

    # Basic overlap detection.
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if _skip_overlap_check(a, b):
                continue
            if _overlap(a[2:], b[2:]):
                problems.append("overlap: {0} overlaps {1}".format(a[0], b[0]))

    if problems:
        for p in problems:
            print("[FAIL] {0}".format(p))
        _err("{0} problem(s) found".format(len(problems)))
        sys.exit(1)
    _ok("Screen OK: {0} element(s), no problems".format(len(elements)))


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _skip_overlap_check(a, b):
    """Ignore decorative/nested overlaps that are normal in HMI compositions."""
    if a[1] == "VisuFbElemLine" or b[1] == "VisuFbElemLine":
        return True
    if a[1] == "VisuFbElemSimple" or b[1] == "VisuFbElemSimple":
        return True
    return _contains(a[2:], b[2:]) or _contains(b[2:], a[2:])


def _contains(outer, inner):
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


def list_types():
    types = _catalog.list_types()
    if not types:
        print("(no catalog types)")
        return
    for t in types:
        try:
            cat = _catalog.load_catalog(t)
            desc = cat.get("description", "")
        except _catalog.CatalogError:
            desc = ""
        print("{0:<14} {1}".format(t, desc))


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


def describe(project_view_dir, type_name, screen=None, folder="", elem=None):
    try:
        catalog = _catalog.load_catalog(type_name)
    except _catalog.CatalogError as exc:
        _err(str(exc))
        sys.exit(1)

    print(
        "Type: {0}  (VisualElementTypeName={1})".format(
            catalog["type"], catalog["visualElementTypeName"]
        )
    )
    if catalog.get("description"):
        print(catalog["description"])
    print("")

    variants = catalog.get("shape_variants")
    if variants:
        print("Shape variants:")
        for k, v in sorted(variants.items()):
            print("  {0:<12} -> {1}".format(k, v))
        print("")

    print("Settable properties:")
    for pname, spec in sorted(catalog.get("params", {}).items()):
        default = _default_for_param(catalog, spec)
        flags = []
        if spec.get("geometry"):
            flags.append("geometry")
        if spec.get("requires"):
            flags.append("requires={0}".format(spec["requires"]))
        flag_s = " [{0}]".format(", ".join(flags)) if flags else ""
        print(
            "  {0:<14} kind={1:<8} default={2!r:<20} {3}{4}".format(
                pname,
                spec.get("kind", ""),
                default,
                spec.get("doc", ""),
                flag_s,
            )
        )
    print("")

    bindings = catalog.get("optional_bindings")
    if bindings:
        print("Optional bindings (variable references):")
        for bname, spec in sorted(bindings.items()):
            print(
                "  {0:<14} member={1:<12} {2}".format(
                    bname, spec.get("member_id"), spec.get("doc", "")
                )
            )
        print("")

    invariants = catalog.get("invariants")
    if invariants:
        print("Invariants:")
        for inv in invariants:
            print("  [{0}] {1}".format(inv.get("severity", "?"), inv.get("rule", "")))
        print("")

    if screen:
        path = _resolve_screen_path(project_view_dir, screen, folder)
        if not os.path.isfile(path):
            _err("Screen file not found: {0}".format(path))
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as handle:
            xml_text = handle.read()
        elements = builder.list_elements(xml_text)
        if elem is None:
            return
        if elem < 0 or elem >= len(elements):
            _err(
                "Element index {0} out of range (0..{1})".format(
                    elem, len(elements) - 1
                )
            )
            sys.exit(1)
        target = elements[elem]
        print(
            "Element #{0}: {1} ({2})".format(elem, target["identifier"], target["type"])
        )
        for mid, m in sorted(target.get("members", {}).items()):
            if m.get("kind") == "color":
                print(
                    "  {0:<12} color={1} canonical={2}".format(
                        mid, m.get("color"), m.get("canonical_name")
                    )
                )
            else:
                print("  {0:<12} {1!r}".format(mid, m.get("value")))


# ---------------------------------------------------------------------------
# new (scaffold an editable SVG skeleton)
# ---------------------------------------------------------------------------

# Layout tokens. Every coordinate in the skeleton is derived from these, so a
# different --w/--h produces a correctly laid-out screen instead of the default
# one with its edges moved. Spacing is on an 8px rhythm; derived widths land on
# 4, which is what ``cts visu lint`` grades against.
_LAYOUT = {
    "margin": 24,    # page margin, all four sides
    "gutter": 16,    # gap between sibling blocks
    "pad": 16,       # padding inside a panel
    "rule": 72,      # y of the rule under the title band
    "action_h": 48,  # button / action-row height
    "side_w": 296,   # preferred width of the right-hand panel
    "card_h": 56,    # KPI card
    "field_h": 32,   # native textfield
    "lamp": 20,      # lamp diameter
    "btn_w": 160,
}


def _snap4(value):
    """Round down to the 4px grid ``cts visu lint`` grades against."""
    return int(value) // 4 * 4


def _snap4_up(value):
    return -(-int(value) // 4) * 4


def compose_skeleton(width=800, height=480, name="", scheme=None):
    """Return a complete, lint-clean SVG skeleton laid out for ``width``x``height``.

    The old seed was a fixed file with four floating examples: resizing the
    canvas moved the edges but left the contents where they were, and a model
    editing it had no layout to preserve. This composes the whole screen from
    :data:`_LAYOUT`, so every size gets a real skeleton -- header band, main
    panel with a KPI row, side panel with fields and lamps, action row.

    Blocks that will not fit are dropped rather than squeezed: a short canvas
    loses the lamp rows, a narrow one falls back to a single KPI card. What is
    emitted is always inside its panel and always passes ``cts visu lint``.

    A non-light *scheme* is written onto the root ``<svg>`` as
    ``data-cds-scheme``, so the sketch carries it and every later command --
    lint, preview, from-svg -- agrees about it without repeating a flag.
    """
    W, H = int(width), int(height)
    L = _LAYOUT
    M, gut, pad = L["margin"], L["gutter"], L["pad"]

    title = name or "Screen title"

    content_w = W - 2 * M
    rule_y = L["rule"]
    body_y = rule_y + gut
    action_y = _snap4(H - M - L["action_h"])
    foot_rule_y = action_y - gut
    body_h = (foot_rule_y - 8) - body_y

    side_w = min(L["side_w"], _snap4(content_w // 2))
    main_w = content_w - gut - side_w
    side_x = M + main_w + gut

    out = []
    add = out.append

    # Only a non-default scheme is stamped: a sketch with no attribute reads as
    # light, and writing "light" everywhere would just be noise the author has
    # to keep in sync.
    from . import style_roles as _style_roles

    scheme_attr = ""
    if _style_roles.normalize_scheme(scheme) != "light":
        scheme_attr = ' data-cds-scheme="{0}"'.format(
            _style_roles.normalize_scheme(scheme)
        )

    add('<svg xmlns="http://www.w3.org/2000/svg" '
        'width="{0}" height="{1}"{2}>'.format(W, H, scheme_attr))
    add("")
    add("  <!-- ============================================================")
    add("       HMI sketch. Edit this file, then, pointing each at this file:")
    add("         cts visu lint      check the design (and snap it with fix)")
    add("         cts visu preview   render a PNG next to it, and look at it")
    add("         cts visu from-svg  compile it into the CODESYS project")
    add("")
    add("       COLOURS: never write one. Put class=\"...\" on the element and")
    add("       the active CODESYS style picks the colour.")
    add("         surfaces  panel  card  divider")
    add("         type      h1 (22)  h2 (16)  value (28)  label (12)  caption (11)")
    add("         emphasis  muted  inverse")
    add("         status    ok  warn  alarm")
    add("         P&ID      pipe-water  metal")
    add("       Buttons, textfields and lamps take NO class: they inherit the")
    add("       native CODESYS control style.")
    if scheme_attr:
        add("")
        add("       This screen is DARK (data-cds-scheme on the root element).")
        add("       Nothing else changes: the same classes resolve to the dark")
        add("       palette, so you still never write a colour. Lamps keep their")
        add("       indicator colours by design; an indicator that changed")
        add("       meaning with the scheme would be a safety problem.")
    add("")
    add("       LAYOUT: {0}px page margin, {1}px between blocks, {2}px panel".format(
        M, gut, pad))
    add("       padding, coordinates on a 4px grid. Keep to it and the screen")
    add("       stays aligned; lint knows how to snap what drifts.")
    add("       The background is painted for you, so never add a full-screen rect.")
    add("       ============================================================ -->")
    add("")

    # --- header band -------------------------------------------------------
    add("  <!-- header: title, secondary caption, rule -->")
    add('  <text class="h1" x="{0}" y="{1}">{2}</text>'.format(M, M + 22, _esc_xml(title)))
    cap_w = min(160, _snap4(content_w // 3))
    add('  <text class="caption" x="{0}" y="40" data-width="{1}" '
        'text-anchor="middle">Line 1 / Shift A</text>'.format(W - M - cap_w, cap_w))
    add('  <line class="divider" x1="{0}" y1="{1}" x2="{2}" y2="{1}"/>'.format(
        M, rule_y, W - M))
    add("")

    # --- main panel --------------------------------------------------------
    add("  <!-- main panel: put the process graphic / trend / table here -->")
    add('  <rect class="panel" x="{0}" y="{1}" width="{2}" height="{3}"/>'.format(
        M, body_y, main_w, body_h))
    add('  <text class="h2" x="{0}" y="{1}">Process</text>'.format(
        M + pad, body_y + pad + 16))

    # KPI row along the bottom of the main panel: card + status accent bar.
    card_y = body_y + body_h - pad - L["card_h"]
    kpis = [("ok", "ACCEPT", "0"), ("warn", "REJECT", "0")]
    inner_w = main_w - 2 * pad
    card_w = _snap4((inner_w - gut) // 2)
    if not _kpi_fits(M + pad, card_w, kpis[0][1]):
        kpis, card_w = kpis[:1], inner_w
    add("  <!-- KPI cards: accent bar + label + live value -->")
    for i, (status, label, fmt) in enumerate(kpis):
        cx = M + pad + i * (card_w + gut)
        add('  <rect class="card" x="{0}" y="{1}" width="{2}" height="{3}" rx="4"/>'
            .format(cx, card_y, card_w, L["card_h"]))
        add('  <rect class="{0}" x="{1}" y="{2}" width="8" height="{3}"/>'.format(
            status, cx, card_y, L["card_h"]))
        add('  <text class="label" x="{0}" y="{1}">{2}</text>'.format(
            cx + 24, card_y + 24, label))
        vx, vw = _kpi_value_box(cx, card_w, label)
        add('  <text class="value" x="{0}" y="{1}" data-width="{2}" data-height="40" '
            'text-anchor="middle">{3}</text>'.format(vx, card_y + 28, vw, fmt))
    add("")

    # --- side panel --------------------------------------------------------
    add("  <!-- side panel: setpoints and state -->")
    add('  <rect class="panel" x="{0}" y="{1}" width="{2}" height="{3}"/>'.format(
        side_x, body_y, side_w, body_h))
    add('  <text class="h2" x="{0}" y="{1}">Setpoints</text>'.format(
        side_x + pad, body_y + pad + 16))

    field_w = side_w - 2 * pad
    fields = [("Line speed", "VisuVars.rLineSpeed", "%3.1f m/min"),
              ("Reject threshold", "VisuVars.rRejectLimit", "%3.1f %%")]
    add("  <!-- textfield: data-width/data-height give it a box, the text content")
    add("       is the format string, data-text-var is what it displays.")
    add("       Its y is a BASELINE like any text, so the box top is y minus the")
    add("       font size. Leave 24px between a label baseline and its field. -->")
    for i, (label, var, fmt) in enumerate(fields):
        top = body_y + 48 + i * 72
        if top + 24 + L["field_h"] + pad > body_y + body_h:
            break
        add('  <text class="label" x="{0}" y="{1}">{2}</text>'.format(
            side_x + pad, top + 12, label))
        add('  <text data-cds-type="textfield" x="{0}" y="{1}" data-width="{2}" '
            'data-height="{3}"'.format(
                side_x + pad, top + 36, field_w, L["field_h"]))
        add('        data-text-var="{0}" font-size="12">{1}</text>'.format(var, fmt))
    add("")

    lamps = [("green", "VisuVars.xRunning", "Running"),
             ("red", "VisuVars.xFault", "Fault")]
    lamp_top = body_y + 192
    if lamp_top + 32 + len(lamps) * 32 <= body_y + body_h:
        add('  <line class="divider" x1="{0}" y1="{1}" x2="{2}" y2="{1}"/>'.format(
            side_x + pad, lamp_top, side_x + side_w - pad))
        add("  <!-- lamp: data-var drives it, data-color is the ON colour -->")
        for i, (color, var, label) in enumerate(lamps):
            ly = lamp_top + 16 + i * 32
            add('  <rect data-cds-type="lamp" x="{0}" y="{1}" width="{2}" height="{2}"'
                .format(side_x + pad, ly, L["lamp"]))
            add('        data-color="{0}" data-var="{1}"/>'.format(color, var))
            add('  <text class="label" x="{0}" y="{1}">{2}</text>'.format(
                side_x + pad + L["lamp"] + 12, ly + 16, label))
        add("")

    # --- action row --------------------------------------------------------
    add("  <!-- action row: buttons left, status banner right -->")
    add('  <line class="divider" x1="{0}" y1="{1}" x2="{2}" y2="{1}"/>'.format(
        M, foot_rule_y, W - M))
    btn_w = min(L["btn_w"], _snap4((main_w - gut) // 2))
    for i, (label, var) in enumerate([("Start", "VisuVars.xStart"),
                                      ("Stop", "VisuVars.xStop")]):
        add('  <rect data-cds-type="button" x="{0}" y="{1}" width="{2}" height="{3}"'
            .format(M + i * (btn_w + gut), action_y, btn_w, L["action_h"]))
        add('        data-text="{0}" data-cds-tap="{1}"/>'.format(label, var))
    add('  <rect class="alarm" x="{0}" y="{1}" width="{2}" height="{3}" rx="4"/>'.format(
        side_x, action_y, side_w, L["action_h"]))
    add('  <text class="inverse" x="{0}" y="{1}" data-width="{2}" data-height="16" '
        'text-anchor="middle">2 active alarms</text>'.format(
            side_x, action_y + 24, side_w))
    add("</svg>")
    return "\n".join(out) + "\n"


def _esc_xml(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _kpi_value_box(card_x, card_w, label):
    """Value box for a KPI card: right of the label, flush with the card's padding."""
    right = card_x + card_w - 16
    x = _snap4_up(card_x + 24 + svg_import._estimate_text_width(label, 12) + 16)
    return x, _snap4(right - x)


def _kpi_fits(card_x, card_w, label):
    return _kpi_value_box(card_x, card_w, label)[1] >= 48


# The smallest canvas the layout blocks are sized against. Below this the
# composition does not degrade further -- it collides, because the header band,
# the panel inset and the action row are fixed costs that stop fitting rather
# than shrinking. 480x320 is the smallest size the skeleton is tested at.
_MIN_CANVAS = (480, 320)


def _check_canvas(width, height):
    """Warn about canvas sizes the composed skeleton is not sound at.

    ``visu new`` used to hand back a skeleton for any numbers it was given, and
    the two ways that goes wrong both produce a file that fails the linter the
    same tool ships -- which reads as the sketch format being broken rather than
    the canvas being outside what the layout can do. Say it here instead, once,
    while the author can still pick a different size.
    """
    if width < _MIN_CANVAS[0] or height < _MIN_CANVAS[1]:
        _warn(
            "Canvas {0}x{1} is below {2}x{3}, the smallest size the layout blocks "
            "fit at -- expect the skeleton to overlap itself. Run `cts visu lint` "
            "and lay it out by hand.".format(
                width, height, _MIN_CANVAS[0], _MIN_CANVAS[1]
            )
        )
    off = [n for n, v in (("--w", width), ("--h", height)) if v % 4]
    if off:
        _warn(
            "{0} {1} not {2} of 4, so the halves the layout computes land off the "
            "4px grid `cts visu lint` enforces. Run it with --fix, or round the "
            "canvas.".format(
                " and ".join(off),
                "is" if len(off) == 1 else "are",
                "a multiple" if len(off) == 1 else "multiples",
            )
        )


def new_svg(out_path, name="", width=800, height=480, scheme=None):
    """Write a ready-to-edit SVG skeleton for the requested canvas size."""
    text = compose_skeleton(width, height, name, scheme)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)

    _ok("Created SVG sketch: {0}".format(out_path))
    _check_canvas(int(width), int(height))
    print(out_path)


# ---------------------------------------------------------------------------
# preview / lint (sketch-level, before compiling)
# ---------------------------------------------------------------------------


def _load_sketch(svg_path, theme_name, project_view_dir, background, scheme=None):
    """Read + parse a sketch, exiting with a clear message on any failure."""
    from . import lint as _lint
    from . import svg_import as _svg_import

    if not os.path.isfile(svg_path):
        _err("SVG file not found: {0}".format(svg_path))
        sys.exit(1)
    with open(svg_path, "r", encoding="utf-8") as handle:
        svg_text = handle.read()

    # Resolved before the theme is loaded: the scheme decides which roles the
    # CODESYS style may own, so a light theme loaded first would be layered over
    # the dark base palette and paint the sketch light again.
    resolved_scheme = _svg_import.read_scheme(svg_text, scheme)
    theme_colors = None
    if theme_name:
        try:
            theme_colors = themes.load_theme(theme_name, resolved_scheme)
        except themes.ThemeError as exc:
            _err(str(exc))
            sys.exit(1)
    try:
        findings, parsed = _lint.lint_svg(
            svg_text,
            theme=theme_colors,
            project_dir=project_view_dir,
            background=background,
            scheme=resolved_scheme,
        )
    except (ValueError, themes.ThemeError) as exc:
        _err(str(exc))
        sys.exit(1)
    return svg_text, findings, parsed


def _print_findings(findings, header=True):
    """Print lint findings grouped by severity; return the error count."""
    if not findings:
        return 0
    if header:
        print("")
    tags = {"error": "[FAIL]", "warn": "[WARN]", "info": "[INFO]"}
    for f in findings:
        print(
            "{0} {1:<13} #{2:<3} {3}".format(
                tags.get(f.severity, "[    ]"), f.rule, f.index, f.message
            )
        )
    return sum(1 for f in findings if f.severity == "error")


def preview_svg(
    project_view_dir,
    svg_path,
    theme_name,
    out_path,
    background,
    grid=0,
    png=True,
    scheme=None,
):
    """Render a sketch to a viewable SVG (and PNG) using the compiler's colours."""
    from . import preview as _preview

    _svg_text, findings, parsed = _load_sketch(
        svg_path, theme_name, project_view_dir, background, scheme
    )

    base = out_path or (os.path.splitext(svg_path)[0] + ".preview.svg")
    if base.lower().endswith(".png"):
        svg_out = os.path.splitext(base)[0] + ".svg"
        png_out = base
    else:
        svg_out = base
        png_out = os.path.splitext(base)[0] + ".png"

    rendered = _preview.render(parsed, parsed.get("theme"), grid=grid)
    with open(svg_out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    _ok("Preview SVG: {0}".format(svg_out))

    written = None
    if png:
        canvas = parsed["canvas"]
        written = _preview.rasterize(
            svg_out, png_out, canvas["width"], canvas["height"]
        )
        if written:
            _ok("Preview PNG: {0}".format(written))
        else:
            _ok(
                "No headless Chrome/Edge found; open the SVG above, or set "
                "CHROME_PATH to rasterise."
            )

    _print_findings(findings)
    print(written or svg_out)


def lint_svg(
    project_view_dir,
    svg_path,
    theme_name,
    background,
    fix=False,
    strict=False,
    scheme=None,
):
    """Check a sketch for the defects that survive compilation but show on screen."""
    from . import lint as _lint

    svg_text, findings, _parsed = _load_sketch(
        svg_path, theme_name, project_view_dir, background, scheme
    )

    if fix:
        # One pass does not settle it. The font-scale rule rewrites font-size,
        # and a <text> baseline is graded through its box top -- which is the
        # baseline minus that very font size. So snapping the grid has to happen
        # again against the new size, and an author who ran --fix once was left
        # holding a file the next lint still complained about. Iterate to a
        # fixed point instead, bounded so a rule that ever disagrees with itself
        # cannot spin here.
        total = 0
        for _ in range(_FIX_PASSES):
            try:
                fixed, count = _lint.apply_fixes(svg_text, findings)
            except ValueError as exc:
                _err(str(exc))
                sys.exit(1)
            if not count:
                break
            total += count
            with open(svg_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(fixed)
            # Re-check so the report reflects the file on disk, not the old one.
            svg_text, findings, _parsed = _load_sketch(
                svg_path, theme_name, project_view_dir, background, scheme
            )
        if total:
            _ok("Fixed {0} attribute(s) in {1}".format(total, svg_path))
        else:
            _ok("Nothing mechanically fixable")
        if any(f.fixable for f in findings):
            _warn(
                "Still fixable after {0} passes -- two rules are disagreeing; "
                "please report this sketch".format(_FIX_PASSES)
            )

    errors = _print_findings(findings, header=False)
    counts = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    if not findings:
        _ok("Sketch OK: no design problems found")
        return
    summary = ", ".join(
        "{0} {1}".format(counts[s], s) for s in ("error", "warn", "info") if s in counts
    )
    _ok("{0} finding(s): {1}".format(len(findings), summary))
    if errors or (strict and findings):
        sys.exit(1)


# ---------------------------------------------------------------------------
# from-svg
# ---------------------------------------------------------------------------


def _create_screen_for_svg(project_view_dir, folder, screen_name, bg_color):
    """Create a new screen file for --create-screen; return (out_path, screen).

    Placement (parent guids, path) is copied from an existing sibling object in
    the target folder. Exits with an error if the folder is empty or the screen
    already exists.
    """
    import os
    import sys

    from . import builder as _builder

    if not screen_name:
        _err("--screen-name is required when --create-screen is used")
        sys.exit(1)
    target_dir = _folder_to_dir(project_view_dir, folder)
    sibling = _builder.find_sibling_object(target_dir)
    if sibling is None:
        _err("Folder contains no existing object to copy placement from.")
        sys.exit(1)
    placement = _builder.read_placement_from_sibling(sibling)
    out_path = os.path.join(target_dir, screen_name + ".xml")
    if os.path.exists(out_path):
        _err("Screen already exists: {0}".format(out_path))
        sys.exit(1)
    xml_text = _builder.build_screen(
        name=screen_name,
        size_x=800,
        size_y=480,
        parent_guid=placement["parent_guid"],
        parent_svnode_guid=placement["parent_svnode_guid"],
        path_segments=placement["path"],
        is_start_visu=False,
        bg_color=bg_color,
    )
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)
    _ok("Created screen {0} at {1}".format(screen_name, out_path))
    return out_path, screen_name


def _append_svg_elements(
    xml_text, elements, project_view_dir, theme_colors, scheme="light"
):
    """Append each parsed SVG element to the screen XML; return the new XML.

    Frame elements load a project-local catalog + golden template; other types
    load a builtin catalog and allocate a Text-ID when they carry literal text.
    Any catalog/builder error is reported and exits.

    *scheme* reaches the builder because native controls (button, textfield)
    normally defer their fill/frame to the CODESYS visual style, and that is only
    correct while the style and the screen agree about how light they are.
    """
    import sys

    from . import builder as _builder
    from . import catalog as _catalog

    textlist_module = None
    for elem_spec in elements:
        type_name = elem_spec["type"]
        params = elem_spec["params"]

        # Frame elements use a project-local catalog + template.
        if type_name == "frame":
            visu = params.get("visu")
            if not visu:
                _err("frame element is missing data-visu attribute")
                sys.exit(1)
            try:
                catalog = _catalog.load_frame_catalog(project_view_dir, visu)
            except _catalog.CatalogError as exc:
                _err(str(exc))
                sys.exit(1)
            try:
                template = _catalog.load_frame_template(project_view_dir, visu)
            except IOError as exc:
                _err("frame template not found: {0}".format(exc))
                sys.exit(1)
            try:
                new_xml, geometry, info = _builder.append_element(
                    xml_text, catalog, params, theme_colors=theme_colors,
                    golden_template_text=template, scheme=scheme,
                )
                xml_text = new_xml
            except _builder.BuilderError as exc:
                _err(str(exc))
                sys.exit(1)
            continue

        try:
            catalog = _catalog.load_catalog(type_name)
        except _catalog.CatalogError as exc:
            _err(str(exc))
            sys.exit(1)

        # Allocate Text-ID if text is present.
        if params.get("text") and not params.get("text_id"):
            if textlist_module is None:
                from . import textlist as _tl

                textlist_module = _tl
            try:
                tid = textlist_module.allocate_text_id(project_view_dir, params["text"])
                params["text_id"] = tid
            except Exception as exc:
                _err("Text-ID allocation failed: {0}".format(exc))
                sys.exit(1)

        try:
            new_xml, geometry, info = _builder.append_element(
                xml_text, catalog, params, theme_colors=theme_colors, scheme=scheme
            )
            xml_text = new_xml
        except _builder.BuilderError as exc:
            _err(str(exc))
            sys.exit(1)

    return xml_text


def _emit_gvl(project_view_dir, elements, gvl_name, gvl_file, output_path):
    """Generate/refresh the GVL for bound runtime variables, or hint if unused."""
    import sys

    from . import gvl as _gvl

    if gvl_name or gvl_file:
        gvl_result, written = _gvl.ensure_gvl_result(
            project_view_dir,
            elements,
            gvl_name=gvl_name or "VisuVars",
            gvl_path=gvl_file,
            warn=lambda msg: _warn("Not declared: {0}".format(msg)),
        )
        if gvl_result and written:
            _ok("Updated GVL: {0}".format(gvl_result))
        elif gvl_result:
            # Every referenced variable is already declared -- here or in
            # another project GVL. Saying "Updated" would send the author
            # looking for declarations this run did not add.
            _ok("All runtime variables already declared; GVL not modified")
        else:
            _ok("No runtime variables detected; GVL not generated")
    elif any(
        elem.get("params", {}).get("text_var")
        or elem.get("params", {}).get("tap_var")
        or elem.get("params", {}).get("toggle_var")
        or elem.get("params", {}).get("configured_inputs")
        or elem.get("params", {}).get("input_actions")
        for elem in elements
    ):
        print(
            "[HINT] SVG contains runtime variable references. "
            "Use --gvl to auto-generate GVL declarations.",
            file=sys.stderr,
        )


def from_svg(
    project_view_dir,
    svg_path,
    screen,
    folder,
    theme_name,
    out_path,
    create_screen,
    screen_name,
    gvl_name=None,
    gvl_file=None,
    background=None,
    preview=True,
    strict=False,
    scheme=None,
):
    """Compile an SVG file to a CODESYS screen XML."""
    import os
    import sys

    from . import lint as _lint
    from . import screen_xml as _screen_xml
    from . import svg_import as _svg_import

    # Read SVG.
    if not os.path.isfile(svg_path):
        _err("SVG file not found: {0}".format(svg_path))
        sys.exit(1)
    with open(svg_path, "r", encoding="utf-8") as handle:
        svg_text = handle.read()

    # Parse SVG (need result early for bg_color when creating screen).
    # The scheme is resolved first: it decides which roles the CODESYS style is
    # allowed to own, so loading the theme without it would layer a light style
    # over the dark base palette and repaint the screen light again.
    resolved_scheme = _svg_import.read_scheme(svg_text, scheme)
    theme_colors = None
    if theme_name:
        try:
            theme_colors = themes.load_theme(theme_name, resolved_scheme)
        except themes.ThemeError as exc:
            _err(str(exc))
            sys.exit(1)

    try:
        findings, result = _lint.lint_svg(
            svg_text,
            theme=theme_colors,
            project_dir=project_view_dir,
            background=background,
            scheme=resolved_scheme,
        )
    except (ValueError, themes.ThemeError) as exc:
        _err(str(exc))
        sys.exit(1)

    # Design findings are advisory: a sketch that compiles is allowed to
    # compile. --strict turns them into a gate for CI or a careful author.
    errors = _print_findings(findings)
    if findings:
        _ok(
            "{0} design finding(s); run 'cts visu lint --svg {1}' for detail".format(
                len(findings), svg_path
            )
        )
    if errors or (strict and findings):
        _err("Refusing to compile (--strict)" if not errors else "Sketch has errors")
        sys.exit(1)

    canvas = result["canvas"]
    elements = result["elements"]
    parsed_theme = result.get("theme")
    bg_color = result.get("bg_color")
    resolved_scheme = result.get("scheme", "light")

    # Merge parsed inline theme over CLI theme.
    if parsed_theme:
        if theme_colors:
            theme_colors = dict(theme_colors, **parsed_theme)
        else:
            theme_colors = parsed_theme

    # Resolve screen target.
    if create_screen:
        out_path, screen = _create_screen_for_svg(
            project_view_dir, folder, screen_name, bg_color
        )

    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)

    # Resize screen if canvas differs.
    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()
    size_x, size_y = _screen_xml.read_screen_size(xml_text)
    if (size_x, size_y) != (canvas["width"], canvas["height"]):
        _ok(
            "Screen size ({0}x{1}) differs from canvas ({2}x{3}); resizing".format(
                size_x, size_y, canvas["width"], canvas["height"]
            )
        )
        xml_text = _screen_xml.resize_screen(
            xml_text, canvas["width"], canvas["height"]
        )

    # If screen already existed and has no custom bg, set from theme.
    if bg_color and not create_screen:
        xml_text = _screen_xml.set_screen_background(xml_text, bg_color)

    # Recompiling replaces the screen, it does not add to it. The sketch is the
    # whole screen, so anything the author took out of the SVG has to leave the
    # screen as well -- and appending meant every rerun stacked a second copy of
    # every element on top of the first.
    if not create_screen:
        stale = len(_screen_xml.list_elements(xml_text))
        if stale:
            xml_text = _screen_xml.clear_elements(xml_text)
            _ok("Replacing {0} existing element(s) in {1}".format(stale, screen))

    # Append each element.
    xml_text = _append_svg_elements(
        xml_text, elements, project_view_dir, theme_colors, resolved_scheme
    )

    # Write output.
    output_path = out_path or path
    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)

    # GVL generation for runtime variables.
    _emit_gvl(project_view_dir, elements, gvl_name, gvl_file, output_path)

    # Preview: an author (or a model) should be able to look at the screen
    # without opening CODESYS. Rendered from the same parse, so it cannot
    # disagree with what was just compiled.
    #
    # Written next to the *sketch*, never next to the output XML: the output
    # usually lives in project-view/, which is a synced mirror of the CODESYS
    # project and has no business holding PNGs.
    if preview:
        from . import preview as _preview

        preview_base = os.path.splitext(svg_path)[0]
        preview_svg_path = preview_base + ".preview.svg"
        with open(preview_svg_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_preview.render(result, theme_colors))
        png = _preview.rasterize(
            preview_svg_path,
            preview_base + ".preview.png",
            canvas["width"],
            canvas["height"],
        )
        _ok("Preview: {0}".format(png or preview_svg_path))

    count = len(elements)
    _ok("Compiled {0} element(s) from SVG to {1}".format(count, output_path))
    print(output_path)


# ---------------------------------------------------------------------------
# to-svg
# ---------------------------------------------------------------------------


def to_svg(project_view_dir, screen, folder, out_path, scheme=None):
    """Decompile a CODESYS screen XML to SVG.

    *scheme* overrides the scheme inferred from the screen's background; the
    result is stamped on the sketch when it is dark, so the decompiled file
    recompiles into the screen it came from.
    """
    import os
    import sys

    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()

    try:
        svg_text = svg_export.screen_to_svg(xml_text, scheme=scheme)
    except (ValueError, svg_export.SvgExportError) as exc:
        _err(str(exc))
        sys.exit(1)

    output_path = out_path or (path.rsplit(".", 1)[0] + ".svg")
    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(svg_text)

    _ok("Decompiled screen to SVG: {0}".format(output_path))
    print(output_path)


# ---------------------------------------------------------------------------
# capture-frame
# ---------------------------------------------------------------------------


def _find_frames_in_xml(xml_text, visu_name):
    """Find VisuFbFrame elements in an XML text whose first non-null
    VisNodeRefs33 matches *visu_name*.

    Returns a list of dicts: ``{element, value_count}``.
    """
    import xml.etree.ElementTree as ET

    from .xml_ns import find_named, strip_ns

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results = []
    for el in root.iter():
        if strip_ns(el.tag) != "Single":
            continue
        type_name = find_named(el, "Single", "VisualElementTypeName")
        if type_name is None or (type_name.text or "").strip() != "VisuFbFrame":
            continue

        # Find first non-null VisNodeRefs33.
        matched = False
        for child in el.iter():
            if strip_ns(child.tag) == "Single" and child.attrib.get("Name") == "VisNodeRefs33":
                t = (child.text or "").strip()
                if t == visu_name:
                    matched = True
                break  # first non-null (or null) -- stop either way

        if not matched:
            continue

        # Count how many param IDs have live values (to prefer value-free).
        from . import builder as _builder

        params, _ = _builder._extract_frame_params(el)
        param_ids = set(p["member_id"] for p in params)
        members = _builder._member_map(el)
        value_count = sum(1 for mid in param_ids if mid in members)

        results.append({"element": el, "value_count": value_count})

    return results


def _find_frame_instance(project_view_dir, visu_name, screen=None, folder=None):
    """Locate a VisuFbFrame element in the project whose first non-null
    VisNodeRefs33 matches *visu_name*.

    Scans screen XML files under ``project_view_dir`` (or a single file if
    *screen* is given). Prefers a **value-free** instance (fewest param
    value members). Returns ``None`` if no match is found.

    Returned dict: ``{element, xml_path, value_count}``.
    """
    import os

    candidates = []

    def _scan_xml(xml_path):
        with open(xml_path, "r", encoding="utf-8") as _fh:
            content = _fh.read()
        found = _find_frames_in_xml(content, visu_name)
        for f in found:
            f["xml_path"] = xml_path
        return found

    if screen:
        xml_path = _resolve_screen_path(project_view_dir, screen, folder)
        if os.path.isfile(xml_path):
            candidates.extend(_scan_xml(xml_path))
    else:
        for dirpath, _dirs, files in os.walk(project_view_dir):
            for fn in files:
                if not fn.endswith(".xml"):
                    continue
                xml_path = os.path.join(dirpath, fn)
                candidates.extend(_scan_xml(xml_path))

    if not candidates:
        return None

    # Prefer value-free (fewest synthesized value members).
    candidates.sort(key=lambda c: c["value_count"])
    return candidates[0]


def capture_frame(project_view_dir, visu_name, screen=None, folder=None):
    """Capture a VisuFbFrame instance into a golden template + catalog.

    1. Locates a matching frame in the project.
    2. Serializes the element to XML text.
    3. Tokenizes it into a golden template (geometry placeholders,
       ``@@IDENTIFIER@@``, ``@@VISUAL_ELEMENT_ID@@``, removes param
       value members, inserts ``@@PARAM_MEMBERS@@``).
    4. Builds a catalog JSON with param metadata.
    5. Writes both to ``<project_view_dir>/.cds-visu/frames/``.
    """
    import json
    import os
    import xml.etree.ElementTree as ET

    from . import builder as _builder

    found = _find_frame_instance(project_view_dir, visu_name, screen, folder)
    if found is None:
        _err("no frame referencing '{0}' found in project".format(visu_name))
        sys.exit(1)

    element = found["element"]

    # Serialize element to XML fragment text.
    fragment = ET.tostring(element, encoding="unicode")

    # Extract params.
    params, _ = _builder._extract_frame_params(element)
    param_ids = set(p["member_id"] for p in params)

    # Tokenize.
    template_text = _builder._tokenize_frame(fragment, param_ids)

    # Build catalog.
    catalog = _builder._build_frame_catalog(visu_name, params)

    # Write output files.
    frames_dir = os.path.join(project_view_dir, ".cds-visu", "frames")
    if not os.path.isdir(frames_dir):
        os.makedirs(frames_dir)

    tmpl_path = os.path.join(frames_dir, visu_name + ".xml.tmpl")
    with open(tmpl_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(template_text)

    cat_path = os.path.join(frames_dir, visu_name + ".json")
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)

    _ok("Captured frame '{0}' -> {1}".format(visu_name, tmpl_path))
    _ok("Catalog -> {0}".format(cat_path))
    _ok("Params: {0}".format(", ".join(p["name"] for p in params)))
    print(tmpl_path)


def _default_for_param(catalog, spec):
    mid = spec.get("member_id")
    for m in catalog.get("base_members", []):
        if m.get("id") == mid:
            if m.get("form") == "color":
                return m.get("color")
            return m.get("value")
    return None

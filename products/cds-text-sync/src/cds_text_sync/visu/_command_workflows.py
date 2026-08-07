# -*- coding: utf-8 -*-
"""Implementation of large visu command workflows."""

# Workflow functions receive the command module namespace at runtime so the
# extraction does not duplicate the shared command helpers.
# ruff: noqa: F821

def run_compose_skeleton(_backend, width=800, height=480, name="", scheme=None):
    globals().update(_backend)
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

def run_from_svg(_backend, 
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
    replace=False,
):
    globals().update(_backend)
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
            project_view_dir, folder, screen_name, bg_color, replace=replace
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


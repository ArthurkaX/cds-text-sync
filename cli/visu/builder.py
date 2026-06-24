# -*- coding: utf-8 -*-
"""
builder.py - Offline engine that GENERATES importable CODESYS visualization XML.

These files are IArchivable sync nodes. To preserve their exact structure and
member order (and avoid ElementTree reserialization dropping/normalizing
content), elements are rendered as faithful XML text fragments and spliced into
a string template. ElementTree is used ONLY for read-only inspection (reading a
sibling's ParentGuid/ParentSVNodeGuid, and listing/checking/describing an
existing screen file).
"""

from __future__ import print_function

import json
import os
import re
import xml.etree.ElementTree as ET

from . import catalog as _catalog

# Member block element type guid (every VisualElemMemberList entry).
_MEMBER_TYPE = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}"
_COLOR_TYPE = "{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}"
_FONT_TYPE = "{9e842eb2-1463-4af2-b605-4fbb17044f94}"
_ROOT_TYPE = "{6198ad31-4b98-445c-927f-3258a0e82fe3}"

# Indentation matching the template / ground-truth file.
_EL = " " * 12  # the <Single Type="{f86c2928...}"> element block indent
_MB = " " * 16  # member block indent inside VisualElemMemberList
_INPUT_ACTIONS = None


class BuilderError(Exception):
    pass


# --------------------------------------------------------------------------
# XML escaping
# --------------------------------------------------------------------------


def _esc(value):
    if value is None:
        value = ""
    value = str(value)
    value = value.replace("&", "&amp;")
    value = value.replace("<", "&lt;")
    value = value.replace(">", "&gt;")
    return value


# --------------------------------------------------------------------------
# Color helpers
# --------------------------------------------------------------------------


def parse_color(value):
    """Parse a color spec into a signed 32-bit ARGB int string (CODESYS form).

    Accepts:
      - 0xAARRGGBB / #AARRGGBB / AARRGGBB hex
      - a plain integer (already CODESYS-encoded, may be negative)
    Returns the value as a string suitable for <Single Name="Color" Type="int">.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    raw = text
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    elif raw.startswith("#"):
        raw = raw[1:]
    is_hex = bool(re.match(r"^[0-9a-fA-F]{1,8}$", raw)) and (
        text.lower().startswith("0x")
        or text.startswith("#")
        or len(raw) in (6, 8)
        and re.match(r"^[0-9a-fA-F]+$", raw)
    )
    if is_hex:
        argb = int(raw, 16)
        if len(raw) <= 6:
            # No alpha given -> opaque.
            argb = 0xFF000000 | argb
        argb &= 0xFFFFFFFF
        if argb >= 0x80000000:
            argb -= 0x100000000
        return str(argb)
    try:
        return str(int(text))
    except ValueError:
        raise BuilderError("Invalid color value: {0}".format(value))


# --------------------------------------------------------------------------
# Member rendering
# --------------------------------------------------------------------------


def _render_color_member(member_id, color_int, canonical_name):
    if not canonical_name:
        raise BuilderError(
            "Color member {0} CanonicalName must be non-empty".format(member_id)
        )
    return (
        '{mb}<Single Type="{mt}" Method="IArchivable">\n'
        '{mb}  <Single Name="Id" Type="long">{id}</Single>\n'
        '{mb}  <List Name="Value" Type="System.Collections.ArrayList">\n'
        '{mb}    <Single Type="{ct}" Method="IArchivable">\n'
        '{mb}      <Single Name="Color" Type="int">{color}</Single>\n'
        '{mb}      <Single Name="CanonicalName" Type="string">{cn}</Single>\n'
        "{mb}    </Single>\n"
        "{mb}  </List>\n"
        "{mb}</Single>\n"
    ).format(
        mb=_MB,
        mt=_MEMBER_TYPE,
        ct=_COLOR_TYPE,
        id=member_id,
        color=color_int,
        cn=_esc(canonical_name),
    )


def _render_color_uint(member_id, unsigned_int):
    """Render a color member as short-form uint literal (no struct, no CanonicalName).

    Per plan_1 \u00a74: uint form is used for primitives when a color override is
    provided OR when the theme default is applied (never style-linked for primitives).
    """
    return (
        '{mb}<Single Type="{mt}" Method="IArchivable">\n'
        '{mb}  <Single Name="Id" Type="long">{id}</Single>\n'
        '{mb}  <Single Name="Value" Type="uint">{val}</Single>\n'
        "{mb}</Single>\n"
    ).format(
        mb=_MB,
        mt=_MEMBER_TYPE,
        id=member_id,
        val=str(unsigned_int),
    )


def _render_font_color_struct(member_id, signed_int):
    """Render a font colour member as struct form.

    CODESYS labels/textfields apply font colour ONLY when the member is a
    struct with CanonicalName; the short-form uint value is silently ignored.
    """
    return (
        '{mb}<Single Type="{mt}" Method="IArchivable">\n'
        '{mb}  <Single Name="Id" Type="long">{id}</Single>\n'
        '{mb}  <List Name="Value" Type="System.Collections.ArrayList">\n'
        '{mb}    <Single Type="{ct}" Method="IArchivable">\n'
        '{mb}      <Single Name="Color" Type="int">{color}</Single>\n'
        '{mb}      <Single Name="CanonicalName" Type="string">Font-Default-Color</Single>\n'
        "{mb}    </Single>\n"
        "{mb}  </List>\n"
        "{mb}</Single>\n"
    ).format(
        mb=_MB,
        mt=_MEMBER_TYPE,
        ct=_COLOR_TYPE,
        id=member_id,
        color=str(signed_int),
    )


def _render_scalar_member(member_id, value_type, value):
    if value == "" or value is None:
        return (
            '{mb}<Single Type="{mt}" Method="IArchivable">\n'
            '{mb}  <Single Name="Id" Type="long">{id}</Single>\n'
            '{mb}  <Single Name="Value" Type="{vt}" />\n'
            "{mb}</Single>\n"
        ).format(mb=_MB, mt=_MEMBER_TYPE, id=member_id, vt=value_type)
    return (
        '{mb}<Single Type="{mt}" Method="IArchivable">\n'
        '{mb}  <Single Name="Id" Type="long">{id}</Single>\n'
        '{mb}  <Single Name="Value" Type="{vt}">{val}</Single>\n'
        "{mb}</Single>\n"
    ).format(mb=_MB, mt=_MEMBER_TYPE, id=member_id, vt=value_type, val=_esc(value))


def _render_font_member(member_id, fd):
    return (
        '{mb}<Single Type="{mt}" Method="IArchivable">\n'
        '{mb}  <Single Name="Id" Type="long">{id}</Single>\n'
        '{mb}  <List Name="Value" Type="System.Collections.ArrayList">\n'
        '{mb}    <Single Type="{ft}" Method="IArchivable">\n'
        '{mb}      <Single Name="FontStyle" Type="int">{FontStyle}</Single>\n'
        '{mb}      <Single Name="AdditionalFontStyle" Type="ushort">{AdditionalFontStyle}</Single>\n'
        '{mb}      <Single Name="ExplicitColor" Type="int">{ExplicitColor}</Single>\n'
        '{mb}      <Single Name="CanonicalName" Type="string">{CanonicalName}</Single>\n'
        '{mb}      <Single Name="FontName" Type="string">{FontName}</Single>\n'
        '{mb}      <Single Name="DisplayName" Type="string" />\n'
        '{mb}      <Single Name="FontSize" Type="int">{FontSize}</Single>\n'
        '{mb}      <Single Name="ScriptIdentification" Type="int">{ScriptIdentification}</Single>\n'
        '{mb}      <Single Name="DoubleFontSize" Type="double">{DoubleFontSize}</Single>\n'
        '{mb}      <Single Name="NamedColor" Type="{ct}" Method="IArchivable">\n'
        '{mb}        <Single Name="Color" Type="int">{ncColor}</Single>\n'
        '{mb}        <Single Name="CanonicalName" Type="string">{ncName}</Single>\n'
        "{mb}      </Single>\n"
        "{mb}    </Single>\n"
        "{mb}  </List>\n"
        "{mb}</Single>\n"
    ).format(
        mb=_MB,
        mt=_MEMBER_TYPE,
        ft=_FONT_TYPE,
        ct=_COLOR_TYPE,
        id=member_id,
        ncColor=_esc(fd["NamedColor"]["Color"]),
        ncName=_esc(fd["NamedColor"]["CanonicalName"]),
        FontStyle=_esc(fd["FontStyle"]),
        AdditionalFontStyle=_esc(fd["AdditionalFontStyle"]),
        ExplicitColor=_esc(fd["ExplicitColor"]),
        CanonicalName=_esc(fd["CanonicalName"]),
        FontName=_esc(fd["FontName"]),
        FontSize=_esc(fd["FontSize"]),
        ScriptIdentification=_esc(fd["ScriptIdentification"]),
        DoubleFontSize=_esc(fd["DoubleFontSize"]),
    )


# --------------------------------------------------------------------------
# Element building
# --------------------------------------------------------------------------


def _resolve_members(catalog, params):
    """Return an ordered list of (member_dict, override) describing the element.

    Applies geometry/shape/color/scalar overrides from ``params`` onto a copy
    of the catalog base_members. Auto-computes Center X/Y. Validates bounds and
    the text/Text-ID invariant. Returns the resolved member tuples plus a dict
    of computed geometry for callers (list/check).
    """
    base = catalog["base_members"]
    geo = catalog.get("geometry", {})
    params_map = catalog.get("params", {})

    # Effective scalar values keyed by member id (as string overrides).
    overrides = {}

    # Geometry first (needed for center computation + bounds).
    def _geo_default(role_id):
        for m in base:
            if m.get("id") == role_id:
                return int(m.get("value", "0"))
        return 0

    x = (
        int(params.get("x"))
        if params.get("x") is not None
        else _geo_default(geo.get("x"))
    )
    y = (
        int(params.get("y"))
        if params.get("y") is not None
        else _geo_default(geo.get("y"))
    )
    w = (
        int(params.get("width"))
        if params.get("width") is not None
        else _geo_default(geo.get("width"))
    )
    h = (
        int(params.get("height"))
        if params.get("height") is not None
        else _geo_default(geo.get("height"))
    )

    overrides[geo["x"]] = str(x)
    overrides[geo["y"]] = str(y)
    overrides[geo["width"]] = str(w)
    overrides[geo["height"]] = str(h)
    overrides[geo["center_x"]] = str(x + w // 2)
    overrides[geo["center_y"]] = str(y + h // 2)

    # Shape.
    if params.get("shape"):
        sv = _catalog.shape_value(catalog, params["shape"])
        if sv is None:
            raise BuilderError(
                "Unknown shape '{0}'. Variants: {1}".format(
                    params["shape"],
                    ", ".join(sorted(catalog.get("shape_variants", {}))),
                )
            )
        overrides[catalog["shape_member_id"]] = sv

    # Color overrides (param name -> color member).
    color_overrides = {}  # member_id -> (color_int, canonical_name)
    for pname in ("fill", "frame", "alarm_frame", "alarm_fill", "alarm_text"):
        if params.get(pname) is not None:
            spec = params_map.get(pname, {})
            mid = spec.get("member_id")
            color_int = parse_color(params[pname])
            color_overrides[mid] = (color_int, spec.get("canonical_name"))

    # Generic scalar overrides driven by the param map.
    for pname, spec in params_map.items():
        if spec.get("kind") in ("color", "shape"):
            continue
        if pname in ("x", "y", "width", "height"):
            continue
        if params.get(pname) is not None:
            overrides[spec["member_id"]] = str(params[pname])

    # Text / Text-ID invariant.
    text_val = params.get("text")
    if text_val:
        raise BuilderError(
            "Text on a {0} requires a GlobalTextList Text ID (member 823443203), "
            "which is not yet supported. Omit --text for now.".format(catalog["type"])
        )

    resolved = []
    for member in base:
        mid = member["id"]
        if member["form"] == "color":
            if mid in color_overrides:
                color_int, cn = color_overrides[mid]
                cn = cn or member.get("canonical_name")
            else:
                color_int, cn = member["color"], member.get("canonical_name")
            resolved.append(("color", mid, color_int, cn))
        elif member["form"] == "font_descriptor":
            resolved.append(("font", mid, catalog["font_descriptor"], None))
        else:
            value = overrides.get(mid, member.get("value", ""))
            resolved.append(("scalar", mid, member["value_type"], value))

    geometry = {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "center_x": x + w // 2,
        "center_y": y + h // 2,
    }
    return resolved, geometry


def validate_bounds(geometry, size_x, size_y):
    """Return a list of error strings for any bounds violation."""
    errors = []
    x, y, w, h = (
        geometry["x"],
        geometry["y"],
        geometry["width"],
        geometry["height"],
    )
    if x < 0 or y < 0:
        errors.append("X and Y must be >= 0 (got X={0}, Y={1})".format(x, y))
    if w <= 0 or h <= 0:
        errors.append("Width and Height must be > 0 (got W={0}, H={1})".format(w, h))
    if x + w > size_x:
        errors.append("X+Width ({0}) exceeds screen SizeX ({1})".format(x + w, size_x))
    if y + h > size_y:
        errors.append("Y+Height ({0}) exceeds screen SizeY ({1})".format(y + h, size_y))
    return errors


def render_element(
    catalog, params, identifier, owning_guid, identification_guid, visual_element_id=0
):
    """Render a full <Single Type="{f86c2928...}"> element block as text."""
    resolved, geometry = _resolve_members(catalog, params)

    member_xml = []
    for entry in resolved:
        kind = entry[0]
        if kind == "color":
            member_xml.append(_render_color_member(entry[1], entry[2], entry[3]))
        elif kind == "font":
            member_xml.append(_render_font_member(entry[1], entry[2]))
        else:
            member_xml.append(_render_scalar_member(entry[1], entry[2], entry[3]))
    members = "".join(member_xml)

    is_rect = "True" if catalog.get("visualElementIsRectangle") else "False"
    block = (
        '{el}<Single Type="{ft}" Method="IArchivable">\n'
        '{el}  <Array Name="ConfiguredComplexInputs" Type="{{1de566f6-72a7-494c-9353-9a418172c96e}}" />\n'
        '{el}  <List Name="Elements" Type="System.Collections.ArrayList" />\n'
        '{el}  <Null Name="VisualElementDescription" />\n'
        '{el}  <Single Name="VisualElemMemberList" Type="{{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}}" Method="IArchivable">\n'
        '{el}    <List Name="VisualElemMemberList" Type="{{a4b83bea-3742-489c-9fe8-d96d68dba7ab}}">\n'
        "{members}"
        "{el}    </List>\n"
        "{el}  </Single>\n"
        '{el}  <Single Name="VisualElementName" Type="string">{vename}</Single>\n'
        '{el}  <Single Name="VisualElementTypeName" Type="string">{vetype}</Single>\n'
        '{el}  <Single Name="VisualElementIsRectangle" Type="bool">{isrect}</Single>\n'
        '{el}  <Single Name="VisualElementIdentifier" Type="string">{ident}</Single>\n'
        '{el}  <Null Name="VisualElementOfflinePaintCommands" />\n'
        '{el}  <Null Name="VisualElementFrameInformation" />\n'
        '{el}  <Dictionary Type="System.Collections.Hashtable" Name="VisualElementInputActions" />\n'
        '{el}  <Single Name="VisualElementIdentification" Type="System.Guid">{idguid}</Single>\n'
        '{el}  <Single Name="VisualElementOwningObjectGuid" Type="System.Guid">{owning}</Single>\n'
        '{el}  <Array Name="LMGuids" Type="System.Guid" />\n'
        '{el}  <Dictionary Type="System.Collections.Hashtable" Name="SubElements" />\n'
        '{el}  <Single Name="VisualElementId" Type="int">{veid}</Single>\n'
        '{el}  <List Name="UserManagementAccessRights" Type="System.Collections.ArrayList" />\n'
        '{el}  <Single Name="AnimationDuration" Type="string">0</Single>\n'
        '{el}  <Single Name="BringToForeground" Type="string" />\n'
        '{el}  <Single Name="ElementVersion" Type="byte">{ver}</Single>\n'
        '{el}  <Null Name="TabOrder" />\n'
        "{el}</Single>\n"
    ).format(
        el=_EL,
        ft="{f86c2928-8614-4cca-824b-e819ac4d58c4}",
        members=members,
        vename=_esc(catalog.get("visualElementName", "")),
        vetype=_esc(catalog["visualElementTypeName"]),
        isrect=is_rect,
        ident=_esc(identifier),
        idguid=identification_guid,
        owning=owning_guid,
        veid=str(visual_element_id),
        ver=catalog.get("elementVersion", 1),
    )
    return block, geometry


def _render_golden_element(
    template,
    catalog,
    params,
    identifier,
    owning_guid,
    identification_guid,
    visual_element_id=0,
    theme_colors=None,
):
    """Render an element by substituting placeholders in a golden (IDE-exported)
    template, instead of synthesizing members.

    Handles color override (uint form for primitives), text/text-id, line-specific
    geometry, and sequential VisualElementId.
    """
    geo = catalog.get("geometry", {})
    base = catalog.get("base_members", [])

    def _geo_default(role_id):
        for m in base:
            if m.get("id") == role_id:
                try:
                    return int(m.get("value", "0"))
                except (ValueError, TypeError):
                    return 0
        return 0

    x = int(params["x"]) if params.get("x") is not None else _geo_default(geo.get("x"))
    y = int(params["y"]) if params.get("y") is not None else _geo_default(geo.get("y"))
    w = (
        int(params["width"])
        if params.get("width") is not None
        else _geo_default(geo.get("width"))
    )
    h = (
        int(params["height"])
        if params.get("height") is not None
        else _geo_default(geo.get("height"))
    )
    center_x = x + w // 2
    center_y = y + h // 2

    # Shape resolution.
    shape_val = None
    if params.get("shape"):
        sv = _catalog.shape_value(catalog, params["shape"])
        if sv is None:
            raise BuilderError(
                "Unknown shape '{0}'. Variants: {1}".format(
                    params["shape"],
                    ", ".join(sorted(catalog.get("shape_variants", {}))),
                )
            )
        shape_val = sv
    elif catalog.get("shape_variants"):
        default_shape = catalog.get("default_shape", "rectangle")
        shape_val = catalog.get("shape_variants", {}).get(
            default_shape, "VISU_ST_RECTANGLE"
        )

    # Line endpoint geometry.
    x1 = params.get("x1")
    y1 = params.get("y1")
    x2 = params.get("x2")
    y2 = params.get("y2")

    # Text / Text-ID.
    text_val = params.get("text", "")
    text_id_val = params.get("text_id", "")
    text_var_val = params.get("text_var", "")
    tap_var_val = params.get("tap_var", "")
    toggle_var_val = params.get("toggle_var", "")
    font_name_val = params.get("font_name", "Arial")
    font_size_val = params.get("font_size", "12")

    # Color override: for primitives, emit themeable colors as uint literals.
    # Controls (button) keep struct form -> no placeholder substitution.
    catalog_tcolors = catalog.get("themeable_colors", {})
    fill_uint = None
    frame_uint = None

    # Resolve font color (needed for any text-bearing element, not just primitives).
    font_expr = params.get("font_color")
    font_color_uint = None
    if font_expr:
        if theme_colors:
            from . import themes as _themes

            try:
                font_color_uint = _themes.resolve_color_unsigned(
                    font_expr, theme_colors
                )
            except _themes.ThemeError:
                font_color_uint = None
        if font_color_uint is None:
            c = parse_color(font_expr)
            if c is not None:
                font_color_uint = str(int(c) & 0xFFFFFFFF)
    if font_color_uint is None:
        # Default: white text
        font_color_uint = "4294967295"

    if catalog_tcolors:
        # Resolve fill color.
        fill_expr = params.get("fill")
        if fill_expr is None:
            # Use theme default.
            if theme_colors:
                from . import themes as _themes

                try:
                    fill_uint = _themes.resolve_color_unsigned(
                        "var(--" + catalog_tcolors["fill"]["role"] + ")", theme_colors
                    )
                except _themes.ThemeError:
                    # Theme role not found -> use solid white
                    fill_uint = "4294967295"
        else:
            if theme_colors:
                from . import themes as _themes

                try:
                    fill_uint = _themes.resolve_color_unsigned(fill_expr, theme_colors)
                except _themes.ThemeError:
                    fill_uint = None
            if fill_uint is None:
                c = parse_color(fill_expr)
                if c is not None:
                    fill_uint = str(int(c) & 0xFFFFFFFF)

        # Resolve frame color.
        frame_expr = params.get("frame")
        if frame_expr is None:
            if theme_colors:
                from . import themes as _themes

                try:
                    frame_uint = _themes.resolve_color_unsigned(
                        "var(--" + catalog_tcolors["frame"]["role"] + ")", theme_colors
                    )
                except _themes.ThemeError:
                    # Theme role not found -> use solid black
                    frame_uint = "4278190080"
        else:
            if theme_colors:
                from . import themes as _themes

                try:
                    frame_uint = _themes.resolve_color_unsigned(
                        frame_expr, theme_colors
                    )
                except _themes.ThemeError:
                    frame_uint = None
            if frame_uint is None:
                c = parse_color(frame_expr)
                if c is not None:
                    frame_uint = str(int(c) & 0xFFFFFFFF)

    block = template
    block = block.replace("@@IDENTIFIER@@", _esc(identifier))
    block = block.replace("@@IDENTIFICATION_GUID@@", identification_guid)
    block = block.replace("@@OWNING_GUID@@", owning_guid)
    block = block.replace("@@VISUAL_ELEMENT_ID@@", str(visual_element_id))
    block = block.replace("@@X@@", str(x))
    block = block.replace("@@Y@@", str(y))
    block = block.replace("@@WIDTH@@", str(w))
    block = block.replace("@@HEIGHT@@", str(h))
    block = block.replace("@@CENTER_X@@", str(center_x))
    block = block.replace("@@CENTER_Y@@", str(center_y))
    if shape_val is not None:
        block = block.replace("@@SHAPE@@", _esc(shape_val))

    # Line endpoints (if template has them).
    if x1 is not None:
        block = block.replace("@@X1@@", str(x1))
    if y1 is not None:
        block = block.replace("@@Y1@@", str(y1))
    if x2 is not None:
        block = block.replace("@@X2@@", str(x2))
    if y2 is not None:
        block = block.replace("@@Y2@@", str(y2))

    # Text / Text-ID (if template has them).
    if "@@TEXT@@" in block:
        block = block.replace("@@TEXT@@", _esc(text_val))
    if "@@TEXT_ID@@" in block:
        block = block.replace("@@TEXT_ID@@", _esc(text_id_val))
    if "@@TEXT_VAR@@" in block:
        block = block.replace("@@TEXT_VAR@@", _esc(text_var_val))
    if "@@TAP_VAR@@" in block:
        block = block.replace("@@TAP_VAR@@", _esc(tap_var_val))
    if "@@CONFIGURED_COMPLEX_INPUTS@@" in block:
        block = block.replace(
            "@@CONFIGURED_COMPLEX_INPUTS@@",
            _render_configured_complex_inputs(params, tap_var_val, toggle_var_val),
        )
    if "@@VISUAL_ELEMENT_INPUT_ACTIONS@@" in block:
        block = block.replace(
            "@@VISUAL_ELEMENT_INPUT_ACTIONS@@",
            _render_visual_element_input_actions(params.get("input_actions", [])),
        )
    if "@@FONT_NAME@@" in block:
        block = block.replace("@@FONT_NAME@@", _esc(font_name_val))
    if "@@FONT_SIZE@@" in block:
        block = block.replace("@@FONT_SIZE@@", str(int(float(font_size_val))))

    # Alignment (label/textfield).
    if "@@H_ALIGN@@" in block:
        h_align = params.get("h_align", "HCENTER")
        block = block.replace("@@H_ALIGN@@", _esc(h_align))
    if "@@V_ALIGN@@" in block:
        v_align = params.get("v_align", "VCENTER")
        block = block.replace("@@V_ALIGN@@", _esc(v_align))

    # Color override placeholders.
    if "@@FILL_COLOR_UINT@@" in block and fill_uint is not None:
        block = block.replace("@@FILL_COLOR_UINT@@", fill_uint)
    if "@@FRAME_COLOR_UINT@@" in block and frame_uint is not None:
        block = block.replace("@@FRAME_COLOR_UINT@@", frame_uint)
    if "@@FONT_COLOR_UINT@@" in block:
        block = block.replace("@@FONT_COLOR_UINT@@", font_color_uint)
    if "@@FONT_COLOR_STRUCT@@" in block:
        fc_int = int(font_color_uint) & 0xFFFFFFFF
        if fc_int >= 0x80000000:
            fc_signed = fc_int - 0x100000000
        else:
            fc_signed = fc_int
        fc_member = _render_font_color_struct(663104332, fc_signed)
        block = block.replace("@@FONT_COLOR_STRUCT@@", fc_member)
    if "@@FONT_COLOR_SIGNED@@" in block:
        fc_int = int(font_color_uint) & 0xFFFFFFFF
        if fc_int >= 0x80000000:
            fc_signed = fc_int - 0x100000000
        else:
            fc_signed = fc_int
        block = block.replace("@@FONT_COLOR_SIGNED@@", str(fc_signed))

    geometry = {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "center_x": center_x,
        "center_y": center_y,
    }
    return block, geometry


def _render_configured_complex_inputs(params, tap_var, toggle_var):
    actions = list(params.get("configured_inputs", []))
    if tap_var:
        actions.append({"type": "tap", "values": {"variable": tap_var}})
    if toggle_var:
        actions.append(
            {
                "type": "toggle",
                "values": {
                    "variable": toggle_var,
                    "toggle_on": params.get("toggle_on", "False"),
                },
            }
        )
    if not actions:
        return (
            '              <Array Name="ConfiguredComplexInputs" '
            'Type="{1de566f6-72a7-494c-9353-9a418172c96e}" />'
        )
    rendered = []
    for item in actions:
        action = _configured_complex_input(item["type"])
        members = _render_complex_input_members(action, item.get("values", {}))
        rendered.append(_render_configured_complex_input(action, members))
    return (
        '              <Array Name="ConfiguredComplexInputs" Type="{1de566f6-72a7-494c-9353-9a418172c96e}">\n'
        + "".join(rendered)
        + "              </Array>"
    )


def _render_configured_complex_input(action, members):
    block = (
        '                <Single Type="{1de566f6-72a7-494c-9353-9a418172c96e}" Method="IArchivable">\n'
        '                  <Null Name="DescriptionTree" />\n'
        '                  <Single Name="VisualElemMemberList" Type="{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}" Method="IArchivable">\n'
        '                    <List Name="VisualElemMemberList" Type="{a4b83bea-3742-489c-9fe8-d96d68dba7ab}">\n'
        "{members}"
        '                    </List>\n'
        '                  </Single>\n'
        '                  <Single Name="SignatureName" Type="string">@@SIGNATURE@@</Single>\n'
        '                  <Single Name="Name" Type="string">@@NAME@@</Single>\n'
        '                  <Single Name="Description" Type="string">@@DESCRIPTION@@</Single>\n'
        '                </Single>\n'
    )
    block = block.replace("{members}", members)
    block = block.replace("@@SIGNATURE@@", _esc(action["signature_name"]))
    block = block.replace("@@NAME@@", _esc(action["name"]))
    block = block.replace("@@DESCRIPTION@@", _esc(action["description"]))
    return block


def _configured_complex_input(name):
    global _INPUT_ACTIONS
    if _INPUT_ACTIONS is None:
        path = os.path.join(os.path.dirname(__file__), "catalog", "input_actions.json")
        with open(path, "r") as f:
            _INPUT_ACTIONS = json.load(f)
    try:
        return _INPUT_ACTIONS["configured_complex_inputs"][name]
    except KeyError:
        raise BuilderError("Unknown configured complex input: {0}".format(name))


def _render_complex_input_members(action, values):
    rendered = []
    for member in action.get("members", []):
        value = values.get(member["name"], "")
        rendered.append(
            '                      <Single Type="{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}" Method="IArchivable">\n'
            '                        <Single Name="Id" Type="long">@@MEMBER_ID@@</Single>\n'
            '                        <Single Name="Value" Type="@@KIND@@">@@VALUE@@</Single>\n'
            '                      </Single>\n'
            .replace("@@MEMBER_ID@@", str(int(member["member_id"])))
            .replace("@@KIND@@", _esc(member.get("kind", "string")))
            .replace("@@VALUE@@", _esc(value))
        )
    return "".join(rendered)


def _visual_input_action(name):
    global _INPUT_ACTIONS
    if _INPUT_ACTIONS is None:
        _configured_complex_input("tap")
    try:
        return _INPUT_ACTIONS["visual_element_input_actions"][name]
    except KeyError:
        raise BuilderError("Unknown visual element input action: {0}".format(name))


def _render_visual_element_input_actions(actions):
    if not actions:
        return (
            '              <Dictionary Type="System.Collections.Hashtable" '
            'Name="VisualElementInputActions" />'
        )
    by_event = {}
    for action in actions:
        by_event.setdefault(action["event"], []).append(action)
    entries = []
    for event in sorted(by_event):
        entries.append(_render_input_action_entry(event, by_event[event]))
    return (
        '              <Dictionary Type="System.Collections.Hashtable" Name="VisualElementInputActions">\n'
        + "".join(entries)
        + "              </Dictionary>"
    )


def _render_input_action_entry(event, actions):
    cfg = _visual_input_action("array_type")
    rendered_actions = []
    for action in actions:
        spec = _visual_input_action(action["type"])
        rendered_actions.append(_render_input_action(spec, action.get("values", {})))
    block = (
        "                <Entry>\n"
        "                  <Key>\n"
        '                    <Single Type="string">@@EVENT@@</Single>\n'
        "                  </Key>\n"
        "                  <Value>\n"
        '                    <Array Type="@@ARRAY_TYPE@@">\n'
        "@@ACTIONS@@"
        "                    </Array>\n"
        "                  </Value>\n"
        "                </Entry>\n"
    )
    return (
        block.replace("@@EVENT@@", _esc(event))
        .replace("@@ARRAY_TYPE@@", _esc(cfg))
        .replace("@@ACTIONS@@", "".join(rendered_actions))
    )


def _render_input_action(spec, values):
    fields = []
    for field in spec.get("fields", []):
        kind = field["kind"]
        xml_name = field["xml_name"]
        if kind == "null":
            fields.append('                        <Null Name="{0}" />\n'.format(_esc(xml_name)))
            continue
        value = values.get(field.get("name"), field.get("default", ""))
        fields.append(
            '                        <Single Name="@@NAME@@" Type="@@TYPE@@">@@VALUE@@</Single>\n'
            .replace("@@NAME@@", _esc(xml_name))
            .replace("@@TYPE@@", _esc(kind))
            .replace("@@VALUE@@", _esc(value))
        )
    return (
        '                      <Single Type="@@TYPE@@" Method="IArchivable">\n'
        + "".join(fields)
        + "                      </Single>\n"
    ).replace("@@TYPE@@", _esc(spec["type"]))


# --------------------------------------------------------------------------
# Sibling discovery
# --------------------------------------------------------------------------


def _strip_ns(tag):
    return tag.split("}")[-1] if "}" in str(tag) else tag


def _find_named(parent, tag_name, name):
    for child in list(parent):
        if _strip_ns(child.tag) == tag_name and child.attrib.get("Name") == name:
            return child
    return None


def read_placement_from_sibling(xml_path):
    """Read (parent_guid, parent_svnode_guid, path_segments) from a sibling .xml.

    Returns a dict or raises BuilderError if the file is not a visu sync node.
    """
    try:
        tree = ET.parse(xml_path)
    except Exception as exc:
        raise BuilderError("Could not parse sibling XML {0}: {1}".format(xml_path, exc))
    root = tree.getroot()

    meta = _find_named(root, "Single", "MetaObject")
    parent_guid = None
    if meta is not None:
        pg = _find_named(meta, "Single", "ParentGuid")
        if pg is not None:
            parent_guid = (pg.text or "").strip()

    svnode = _find_named(root, "Single", "ParentSVNodeGuid")
    svnode_guid = (svnode.text or "").strip() if svnode is not None else None

    path_arr = _find_named(root, "Array", "Path")
    segments = []
    if path_arr is not None:
        for seg in list(path_arr):
            if _strip_ns(seg.tag) == "Single":
                segments.append((seg.text or "").strip())

    if not parent_guid or not svnode_guid:
        raise BuilderError(
            "Sibling {0} is missing ParentGuid/ParentSVNodeGuid".format(xml_path)
        )
    return {
        "parent_guid": parent_guid,
        "parent_svnode_guid": svnode_guid,
        "path": segments,
    }


def find_sibling_object(folder, exclude=None):
    """Return the path to an existing visu/object .xml in ``folder``, or None.

    Skips ``.cds-object.xml`` (the folder's own container descriptor -- it carries
    the FOLDER's placement, not a child's: its ParentGuid is empty and its Path
    stops at the parent level, so copying from it would mis-place a new child).
    Only a real sibling OBJECT (root Type {6198ad31...}) is a valid placement source.
    """
    if not os.path.isdir(folder):
        return None
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".xml"):
            continue
        if name.lower().endswith(".cds-object.xml"):
            continue
        if exclude and name == exclude:
            continue
        full = os.path.join(folder, name)
        try:
            tree = ET.parse(full)
        except Exception:
            continue
        root = tree.getroot()
        root_type = (root.attrib.get("Type") or "").strip()
        if root_type != _ROOT_TYPE:
            continue
        if _find_named(root, "Single", "ParentSVNodeGuid") is not None:
            return full
    return None


# --------------------------------------------------------------------------
# Screen building
# --------------------------------------------------------------------------

_FIXED_GUID = "11111111-1111-1111-1111-111111111111"


def build_screen(
    name,
    size_x,
    size_y,
    parent_guid,
    parent_svnode_guid,
    path_segments,
    is_start_visu=False,
    visu_guid=None,
    bg_color=None,
):
    """Render a new (empty) screen XML file as text.

    If ``bg_color`` is provided (as an ARGB hex string like "#FF3FF0C1" or
    "0xFF3FF0C1"), the screen background is set to that colour.
    """
    template = _catalog.load_screen_template()
    path_xml = "".join(
        '{0}<Single Type="string">{1}</Single>\n'.format(" " * 8, _esc(seg))
        for seg in (path_segments or [])
    )
    text = template
    text = text.replace("@@VISU_GUID@@", visu_guid or _FIXED_GUID)
    text = text.replace("@@PARENT_GUID@@", parent_guid)
    text = text.replace("@@PARENT_SVNODE_GUID@@", parent_svnode_guid)
    text = text.replace("@@NAME@@", _esc(name))
    text = text.replace("@@SIZE_X@@", str(size_x))
    text = text.replace("@@SIZE_Y@@", str(size_y))
    text = text.replace("@@IS_START_VISU@@", "True" if is_start_visu else "False")
    text = text.replace("@@UNIQUE_ID_GENERATOR@@", "1")
    text = text.replace("@@LAST_USED_ID@@", "1")
    text = text.replace("@@ELEMENTS@@", "")
    text = text.replace("@@PATH@@", path_xml)

    # Background colour.
    if bg_color:
        raw = bg_color.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        elif raw.lower().startswith("0x"):
            raw = raw[2:]
        if raw:
            argb = int(raw, 16)
            if len(raw) <= 6:
                argb |= 0xFF000000  # opaque
            # Signed int for CODESYS.
            if argb >= 0x80000000:
                bg_signed = argb - 0x100000000
            else:
                bg_signed = argb
            text = text.replace("@@BG_ACTIVE@@", "True")
            text = text.replace("@@BG_COLOR@@", str(bg_signed))
            text = text.replace("@@BG_COLOR_FALLBACK@@", str(bg_signed))
        else:
            text = text.replace("@@BG_ACTIVE@@", "False")
            text = text.replace("@@BG_COLOR@@", "16777215")
            text = text.replace("@@BG_COLOR_FALLBACK@@", "16777215")
    else:
        text = text.replace("@@BG_ACTIVE@@", "False")
        text = text.replace("@@BG_COLOR@@", "16777215")
        text = text.replace("@@BG_COLOR_FALLBACK@@", "16777215")

    return text


# --------------------------------------------------------------------------
# Screen file inspection / mutation (text-faithful)
# --------------------------------------------------------------------------


def read_screen_size(xml_text):
    """Return (size_x, size_y) parsed from a screen file's MetaObject."""
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise BuilderError("Could not parse screen XML: {0}".format(exc))
    size_x = size_y = None
    for el in root.iter():
        if _strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeX":
            size_x = int((el.text or "0").strip())
        elif _strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeY":
            size_y = int((el.text or "0").strip())
    if size_x is None or size_y is None:
        raise BuilderError("Screen file has no SizeX/SizeY")
    return size_x, size_y


def read_owning_guid(xml_text):
    """Return the visu's own Guid (MetaObject.Guid)."""
    root = ET.fromstring(xml_text)
    meta = _find_named(root, "Single", "MetaObject")
    if meta is not None:
        guid = _find_named(meta, "Single", "Guid")
        if guid is not None and guid.text:
            return guid.text.strip()
    return _FIXED_GUID


def _read_int_member(xml_text, name):
    root = ET.fromstring(xml_text)
    for el in root.iter():
        if _strip_ns(el.tag) == "Single" and el.attrib.get("Name") == name:
            try:
                return int((el.text or "0").strip())
            except ValueError:
                return 0
    return 0


def list_elements(xml_text):
    """Return a list of dicts describing each element in the screen."""
    root = ET.fromstring(xml_text)
    velist = None
    for el in root.iter():
        if _strip_ns(el.tag) == "List" and el.attrib.get("Name") == "VisualElementList":
            velist = el
            break
    results = []
    if velist is None:
        return results
    for idx, el in enumerate(list(velist)):
        if _strip_ns(el.tag) != "Single":
            continue
        info = {
            "index": idx,
            "type": _named_text(el, "VisualElementTypeName"),
            "name": _named_text(el, "VisualElementName"),
            "identifier": _named_text(el, "VisualElementIdentifier"),
        }
        members = _member_map(el)
        info["members"] = members
        for friendly, mid in (
            ("x", 1649127785),
            ("y", 357335551),
            ("width", 2422045748),
            ("height", 2134141914),
            ("center_x", 550940142),
            ("center_y", 1473355128),
        ):
            info[friendly] = members.get(mid, {}).get("value")
        results.append(info)
    return results


def _named_text(parent, name):
    child = _find_named(parent, "Single", name)
    return (child.text or "").strip() if child is not None and child.text else ""


def _member_map(element):
    """Map member id -> {value, kind, color, canonical_name} for one element."""
    out = {}
    member_container = _find_named(element, "Single", "VisualElemMemberList")
    mlist = (
        _find_named(member_container, "List", "VisualElemMemberList")
        if member_container is not None
        else None
    )
    if mlist is None:
        return out
    for member in list(mlist):
        if _strip_ns(member.tag) != "Single":
            continue
        idc = _find_named(member, "Single", "Id")
        if idc is None or not idc.text:
            continue
        mid = int(idc.text.strip())
        scalar = _find_named(member, "Single", "Value")
        if scalar is not None:
            out[mid] = {"kind": "scalar", "value": (scalar.text or "")}
            continue
        listval = _find_named(member, "List", "Value")
        if listval is not None:
            inner = list(listval)
            if inner and _find_named(inner[0], "Single", "Color") is not None:
                color_el = _find_named(inner[0], "Single", "Color")
                cn_el = _find_named(inner[0], "Single", "CanonicalName")
                out[mid] = {
                    "kind": "color",
                    "color": (color_el.text or "").strip()
                    if color_el is not None
                    else "",
                    "canonical_name": (cn_el.text or "") if cn_el is not None else "",
                }
            else:
                out[mid] = {"kind": "list", "value": None}
    return out


def append_element(xml_text, catalog, params, theme_colors=None):
    """Append a new element to a screen file's VisualElementList.

    Bumps UniqueIdGenerator and LastUsedIdForIdentifier, assigns a
    GenElemInst_N identifier, enforces bounds, and assigns a sequential
    VisualElementId. Returns (new_xml, geometry, info).
    """
    size_x, size_y = read_screen_size(xml_text)
    owning_guid = read_owning_guid(xml_text)

    # Count existing elements for sequential VisualElementId.
    existing = list_elements(xml_text)
    visual_element_id = len(existing)

    last_used = _read_int_member(xml_text, "LastUsedIdForIdentifier")
    unique_id = _read_int_member(xml_text, "UniqueIdGenerator")
    next_id = last_used + 1
    identifier = "GenElemInst_{0}".format(next_id)
    identification_guid = "{0:08x}-0000-4000-8000-000000000000".format(
        next_id & 0xFFFFFFFF
    )

    golden_tmpl_name = catalog.get("golden_template")
    if golden_tmpl_name:
        template = _catalog.load_element_template(golden_tmpl_name)
        block, geometry = _render_golden_element(
            template,
            catalog,
            params,
            identifier,
            owning_guid,
            identification_guid,
            visual_element_id=visual_element_id,
            theme_colors=theme_colors,
        )
    else:
        block, geometry = render_element(
            catalog,
            params,
            identifier,
            owning_guid,
            identification_guid,
            visual_element_id=visual_element_id,
        )

    bound_errors = validate_bounds(geometry, size_x, size_y)
    if bound_errors:
        raise BuilderError("; ".join(bound_errors))

    # Insert the block just before the closing </List> of VisualElementList.
    marker = (
        '<List Name="VisualElementList" Type="{ef9d0b20-c96e-48db-b361-2ded4063150e}">'
    )
    start = xml_text.find(marker)
    if start < 0:
        raise BuilderError("Screen file has no VisualElementList")
    # Walk forward counting nesting depth to find the matching </List>.
    # Self-closing <List ... /> tags (no </List>) are skipped.
    pos = start + len(marker)
    depth = 0
    close = -1
    while True:
        next_open = xml_text.find("<List", pos)
        next_close = xml_text.find("</List>", pos)
        if next_close < 0:
            raise BuilderError("Malformed VisualElementList (no closing tag)")
        if next_open >= 0 and next_open < next_close:
            # Check if this is a self-closing tag (ends with /> before any >).
            tag_end = xml_text.find(">", next_open)
            is_self_closing = (
                tag_end >= 0 and xml_text[tag_end - 1 : tag_end + 1] == "/>"
            )
            if not is_self_closing:
                depth += 1
            pos = next_open + 5
        else:
            if depth == 0:
                close = next_close
                break
            depth -= 1
            pos = next_close + 6
    new_xml = xml_text[:close] + block + xml_text[close:]

    # Bump counters.
    new_xml = _replace_int_member(new_xml, "LastUsedIdForIdentifier", next_id)
    new_xml = _replace_int_member(
        new_xml, "UniqueIdGenerator", unique_id + 1, as_string=True
    )

    info = {
        "identifier": identifier,
        "type": catalog["type"],
        "geometry": geometry,
    }
    return new_xml, geometry, info


def _replace_int_member(xml_text, name, value, as_string=False):
    if as_string:
        pattern = r'(<Single Name="{0}" Type="string">)[^<]*(</Single>)'.format(
            re.escape(name)
        )
    else:
        pattern = r'(<Single Name="{0}" Type="int">)[^<]*(</Single>)'.format(
            re.escape(name)
        )
    repl = r"\g<1>{0}\g<2>".format(value)
    return re.sub(pattern, repl, xml_text, count=1)

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

import os
import re
import xml.etree.ElementTree as ET

from . import catalog as _catalog
from . import builder_inputs as _builder_inputs
from . import screen_xml as _screen_xml
from ._builder_base import (
    BuilderError,
    _COLOR_TYPE,
    _EL,
    _FONT_TYPE,
    _MB,
    _MEMBER_TYPE,
    _ROOT_TYPE,
    _esc,
)
from .xml_ns import find_named, strip_ns

# Re-exported so commands.py can call them via the builder facade.
read_screen_size = _screen_xml.read_screen_size
list_elements = _screen_xml.list_elements

# Re-exported so _render_golden_element and the test suite reach the
# input-action renderers via the builder facade (their logic lives in
# builder_inputs; the lazy _INPUT_ACTIONS cache lives there too).
_render_frame_param_members = _builder_inputs._render_frame_param_members
_render_configured_complex_inputs = _builder_inputs._render_configured_complex_inputs
_render_configured_complex_input = _builder_inputs._render_configured_complex_input
_configured_complex_input = _builder_inputs._configured_complex_input
_render_complex_input_members = _builder_inputs._render_complex_input_members
_visual_input_action = _builder_inputs._visual_input_action
_render_visual_element_input_actions = _builder_inputs._render_visual_element_input_actions
_render_input_action_entry = _builder_inputs._render_input_action_entry
_render_input_action = _builder_inputs._render_input_action

# --------------------------------------------------------------------------
# Frame capture / tokenization helpers (spec 1/2 -- capture-frame)
# --------------------------------------------------------------------------

# Member IDs whose <Value> text becomes a template placeholder.
_FRAME_TOKEN_GEOMETRY = {
	1649127785: "@@X@@",
	357335551: "@@Y@@",
	2422045748: "@@WIDTH@@",
	2134141914: "@@HEIGHT@@",
	550940142: "@@CENTER_X@@",
	1473355128: "@@CENTER_Y@@",
}


def _member_map(element):
	"""Map member id -> {value, kind, color, canonical_name} for one element.

	Duplicated from screen_xml._member_map for convenience (avoids extra
	cross-module coupling in the frame-capture code path).
	"""
	out = {}
	member_container = find_named(element, "Single", "VisualElemMemberList")
	mlist = (
		find_named(member_container, "List", "VisualElemMemberList")
		if member_container is not None
		else None
	)
	if mlist is None:
		return out
	for member in list(mlist):
		if strip_ns(member.tag) != "Single":
			continue
		idc = find_named(member, "Single", "Id")
		if idc is None or not idc.text:
			continue
		mid = int(idc.text.strip())
		scalar = find_named(member, "Single", "Value")
		if scalar is not None:
			out[mid] = {"kind": "scalar", "value": (scalar.text or "")}
			continue
		listval = find_named(member, "List", "Value")
		if listval is not None:
			inner = list(listval)
			if inner and find_named(inner[0], "Single", "Color") is not None:
				color_el = find_named(inner[0], "Single", "Color")
				cn_el = find_named(inner[0], "Single", "CanonicalName")
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


def _extract_frame_params(element):
	"""Extract interface params from a VisuFbFrame *element*.

	Returns ``(params_list, visu_name)`` where each param dict has keys
	``name``, ``member_id``, ``iec_type``, ``default``.
	Uses the same traversal as ``svg_export._render_frame``.
	"""
	# Build parent map for navigating descendants.
	parents = {c: p for p in element.iter() for c in p}

	# First non-null VisNodeRefs33 -> visu name + its holder element.
	visu_name = ""
	holder = None
	for child in element.iter():
		if strip_ns(child.tag) == "Single" and child.attrib.get("Name") == "VisNodeRefs33":
			text = (child.text or "").strip()
			if text:
				visu_name = text
				holder = parents.get(child)
				break

	if holder is None:
		return [], ""

	# Read live member values (to extract defaults).
	member_values = _member_map(element)

	params = []
	for direct_child in list(holder):
		if strip_ns(direct_child.tag) == "List" and direct_child.attrib.get("Name") == "TypeNodeChildren":
			for param_node in list(direct_child):
				if strip_ns(param_node.tag) != "Single":
					continue
				pname_el = find_named(param_node, "Single", "TypeNodeName")
				pid_el = find_named(param_node, "Single", "TypeNodeIdLong")
				if pname_el is None or pid_el is None:
					continue
				pname = (pname_el.text or "").strip()
				if not pname:
					continue
				try:
					pid = int(pid_el.text.strip())
				except (ValueError, TypeError):
					continue

				iec_type = ""
				type_node = find_named(param_node, "Single", "TypeNodeType")
				if type_node is not None:
					qn = find_named(type_node, "Single", "QualifiedName")
					if qn is not None and qn.text:
						iec_type = qn.text.strip()

				default = ""
				m = member_values.get(pid, {})
				if m.get("value") is not None:
					default = m["value"]

				params.append({
					"name": pname,
					"member_id": pid,
					"iec_type": iec_type,
					"default": default,
				})
			break
	return params, visu_name


def _tokenize_frame(fragment_text, param_ids):
	"""Tokenize a VisuFbFrame XML *fragment_text* into a golden template.

	*param_ids* is a set of member IDs whose value members should be
	removed from the top VisualElemMemberList. Returns the template text
	with ``@@X@@``, ``@@Y@@``, ``@@WIDTH@@``, ``@@HEIGHT@@``,
	``@@CENTER_X@@``, ``@@CENTER_Y@@``, ``@@IDENTIFIER@@``,
	``@@VISUAL_ELEMENT_ID@@``, and ``@@PARAM_MEMBERS@@`` placeholders.
	"""
	text = fragment_text

	# 1. Tokenize geometry member values.
	for mid, placeholder in _FRAME_TOKEN_GEOMETRY.items():
		id_marker = '<Single Name="Id" Type="long">' + str(mid) + '</Single>'
		idx = text.find(id_marker)
		if idx < 0:
			continue
		val_tag = '<Single Name="Value"'
		val_idx = text.find(val_tag, idx)
		if val_idx < 0:
			continue
		tag_close = text.find('>', val_idx)
		if tag_close < 0:
			continue
		val_close = text.find('</Single>', tag_close)
		if val_close < 0:
			continue
		text = text[:tag_close + 1] + placeholder + text[val_close:]

	# 2. Tokenize GenElemInst_N identifier.
	text = re.sub(
		r'(VisualElementIdentifier" Type="string">)GenElemInst_\d+(</Single>)',
		r'\1@@IDENTIFIER@@\2',
		text,
	)

	# 3. Tokenize VisualElementId int value.
	text = re.sub(
		r'(VisualElementId" Type="int">)\d+(</Single>)',
		r'\1@@VISUAL_ELEMENT_ID@@\2',
		text,
	)

	# 4. Remove param value members from the top VisualElemMemberList and
	#    insert @@PARAM_MEMBERS@@ before its closing </List>.
	list_marker = '<List Name="VisualElemMemberList"'
	list_start = text.find(list_marker)
	if list_start < 0:
		return text

	# Find matching close (handle nested <List> depth).
	pos = text.find('>', list_start) + 1
	depth = 0
	close_pos = -1
	i = pos
	while i < len(text):
		next_open = text.find('<List', i)
		next_close = text.find('</List>', i)
		if next_close < 0:
			break
		if next_open >= 0 and next_open < next_close:
			tag_end = text.find('>', next_open)
			is_self_closing = tag_end >= 0 and text[tag_end - 1:tag_end + 1] == '/>'
			if not is_self_closing:
				depth += 1
			i = tag_end + 1 if tag_end >= 0 else next_open + 5
		else:
			if depth == 0:
				close_pos = next_close
				break
			depth -= 1
			i = next_close + 6

	if close_pos < 0:
		return text

	after_open = text.index('>', list_start) + 1
	list_content = text[after_open:close_pos]

	# Remove member blocks whose <Id> is in param_ids.
	def _drop_if_param(m):
		block = m.group(0)
		_idm = re.search(r'<Single Name="Id" Type="long">(\d+)</Single>', block)
		if _idm and int(_idm.group(1)) in param_ids:
			return ""
		return block

	member_re = re.compile(
		r'<Single Type="\{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02\}" Method="IArchivable">'
		r'.*?</Single>',
		re.DOTALL,
	)
	cleaned = member_re.sub(_drop_if_param, list_content)
	cleaned = cleaned.rstrip()
	indent_member = " " * 16
	indent_list = " " * 12
	new_content = cleaned + "\n" + indent_member + "@@PARAM_MEMBERS@@\n" + indent_list
	text = text[:after_open] + new_content + text[close_pos:]
	return text


def _build_frame_catalog(visu_name, params):
	"""Build a frame catalog dict for a captured golden template.

	Returns a dict suitable for writing as ``<visu_name>.json``.
	"""
	return {
		"type": "frame",
		"visualElementTypeName": "VisuFbFrame",
		"visu": visu_name,
		"golden_template": visu_name + ".xml.tmpl",
		"base_members": [],
		"params": [
			{
				"name": p["name"],
				"member_id": p["member_id"],
				"iec_type": p["iec_type"],
				"default": p["default"],
			}
			for p in params
		],
	}


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


def _resolve_uint_color(expr, theme_colors, fallback_uint):
    """Resolve a color expression to an unsigned ARGB uint string.

    1. If *expr* is None or empty, return *fallback_uint*.
    2. Try theme-based resolution (``var(--role)`` or hex).
    3. Fall back to raw ``parse_color``.
    4. If all else fails, return *fallback_uint*.
    """
    if not expr:
        return fallback_uint
    if theme_colors:
        from . import themes as _themes

        try:
            result = _themes.resolve_color_unsigned(expr, theme_colors)
            if result is not None:
                return result
        except _themes.ThemeError:
            pass
    c = parse_color(expr)
    if c is not None:
        return str(int(c) & 0xFFFFFFFF)
    return fallback_uint


def _resolve_theme_role_uint(role, theme_colors, fallback_uint):
    """Resolve a theme role name to an unsigned ARGB uint string.

    Builds ``var(--<role>)`` and resolves against *theme_colors*.
    Returns *fallback_uint* if the role is not found or no theme is active.
    """
    if not theme_colors:
        return fallback_uint
    from . import themes as _themes

    try:
        return _themes.resolve_color_unsigned("var(--" + role + ")", theme_colors)
    except _themes.ThemeError:
        return fallback_uint


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


def _remove_color_uint_placeholder(block, member_id):
    """Remove an unresolved short-form color override from a template block."""
    pattern = re.compile(
        r"\n[ \t]*<Single Type=\"\{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02\}\" "
        r"Method=\"IArchivable\">\n"
        r"[ \t]*<Single Name=\"Id\" Type=\"long\">"
        + re.escape(str(member_id))
        + r"</Single>\n"
        r"[ \t]*<Single Name=\"Value\" Type=\"uint\">@@(?:FILL|FRAME)_COLOR_UINT@@"
        r"</Single>\n"
        r"[ \t]*</Single>",
        re.MULTILINE,
    )
    return pattern.sub("", block)


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


def _resolve_golden_geometry(catalog, params):
    """Resolve x/y/width/height (+ center) for a golden-template element.

    Each dimension comes from ``params`` when supplied, else falls back to the
    matching base-member value declared by the template's geometry roles.
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
    return {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "center_x": x + w // 2,
        "center_y": y + h // 2,
    }


def _resolve_golden_colors(catalog, params, theme_colors):
    """Resolve (fill, frame, font) color uints for a golden-template element.

    ``fill``/``frame`` stay None when the element keeps its CODESYS visual-style
    color -- native controls (button/textfield) with no explicit SVG fill/stroke.
    Custom primitives fall back to their theme role (or signed default). Font
    color always resolves, defaulting to opaque white.
    """
    catalog_tcolors = catalog.get("themeable_colors", {})
    native_style_defaults = catalog.get("type") in ("button", "textfield")
    fill_uint = None
    frame_uint = None

    # Resolve font color (needed for any text-bearing element, not just primitives).
    font_color_uint = _resolve_uint_color(
        params.get("font_color"), theme_colors, "4294967295"
    )

    if catalog_tcolors:
        # Resolve fill color.
        fill_expr = params.get("fill")
        fill_role = catalog_tcolors.get("fill", {})
        if fill_expr is None:
            # Use theme default for custom primitives only.
            if not native_style_defaults:
                if theme_colors and fill_role.get("role"):
                    fill_uint = _resolve_theme_role_uint(
                        fill_role["role"],
                        theme_colors,
                        str(int(fill_role.get("default_signed", -1)) & 0xFFFFFFFF),
                    )
                else:
                    fill_uint = str(
                        int(fill_role.get("default_signed", -1)) & 0xFFFFFFFF
                    )
        else:
            fill_uint = _resolve_uint_color(fill_expr, theme_colors, None)

        # Resolve frame color.
        frame_expr = params.get("frame")
        frame_role = catalog_tcolors.get("frame", {})
        if frame_expr is None:
            if not native_style_defaults:
                if theme_colors and frame_role.get("role"):
                    frame_uint = _resolve_theme_role_uint(
                        frame_role["role"],
                        theme_colors,
                        str(
                            int(frame_role.get("default_signed", -16777216))
                            & 0xFFFFFFFF
                        ),
                    )
                else:
                    frame_uint = str(
                        int(frame_role.get("default_signed", -16777216)) & 0xFFFFFFFF
                    )
        else:
            frame_uint = _resolve_uint_color(frame_expr, theme_colors, None)

    return fill_uint, frame_uint, font_color_uint


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
    geometry = _resolve_golden_geometry(catalog, params)
    x = geometry["x"]
    y = geometry["y"]
    w = geometry["width"]
    h = geometry["height"]
    center_x = geometry["center_x"]
    center_y = geometry["center_y"]

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

    # Color override: custom primitives get theme defaults; native controls keep
    # CODESYS visual-style colors unless SVG supplies fill/stroke. catalog_tcolors
    # is retained here to drop unused color placeholders below.
    catalog_tcolors = catalog.get("themeable_colors", {})
    fill_uint, frame_uint, font_color_uint = _resolve_golden_colors(
        catalog, params, theme_colors
    )

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
    elif "@@FILL_COLOR_UINT@@" in block and "fill" in catalog_tcolors:
        block = _remove_color_uint_placeholder(
            block, catalog_tcolors["fill"]["member_id"]
        )
    if "@@FRAME_COLOR_UINT@@" in block and frame_uint is not None:
        block = block.replace("@@FRAME_COLOR_UINT@@", frame_uint)
    elif "@@FRAME_COLOR_UINT@@" in block and "frame" in catalog_tcolors:
        block = _remove_color_uint_placeholder(
            block, catalog_tcolors["frame"]["member_id"]
        )
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

    # Generic catalog-driven placeholders. A catalog may declare a
    # "template_params" map so new element types can bind arbitrary members
    # (lamp style role, image reference, combobox variable, alarm filter, ...)
    # to their template without a per-type branch here:
    #
    #   "template_params": {
    #       "STYLE_ROLE": {"param": "style_role", "default": "..."},
    #       "VAR":        {"param": "var",        "default": ""}
    #   }
    #
    # Each entry maps placeholder "@@STYLE_ROLE@@" to params["style_role"],
    # falling back to "default" (or "" if absent). Values are XML-escaped.
    for placeholder, spec in catalog.get("template_params", {}).items():
        token = "@@{0}@@".format(placeholder)
        if token not in block:
            continue
        param_name = spec.get("param", placeholder.lower())
        value = params.get(param_name)
        if value is None:
            value = spec.get("default", "")
        block = block.replace(token, _esc(str(value)))

    # Frame param members.
    if "@@PARAM_MEMBERS@@" in block:
        block = block.replace(
            "@@PARAM_MEMBERS@@",
            _render_frame_param_members(catalog, params),
        )

    return block, geometry


# --------------------------------------------------------------------------
# Sibling discovery
# --------------------------------------------------------------------------


def read_placement_from_sibling(xml_path):
    """Read (parent_guid, parent_svnode_guid, path_segments) from a sibling .xml.

    Returns a dict or raises BuilderError if the file is not a visu sync node.
    """
    try:
        tree = ET.parse(xml_path)
    except Exception as exc:
        raise BuilderError("Could not parse sibling XML {0}: {1}".format(xml_path, exc))
    root = tree.getroot()

    meta = find_named(root, "Single", "MetaObject")
    parent_guid = None
    if meta is not None:
        pg = find_named(meta, "Single", "ParentGuid")
        if pg is not None:
            parent_guid = (pg.text or "").strip()

    svnode = find_named(root, "Single", "ParentSVNodeGuid")
    svnode_guid = (svnode.text or "").strip() if svnode is not None else None

    path_arr = find_named(root, "Array", "Path")
    segments = []
    if path_arr is not None:
        for seg in list(path_arr):
            if strip_ns(seg.tag) == "Single":
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
        if find_named(root, "Single", "ParentSVNodeGuid") is not None:
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
# Screen file inspection / mutation
# (moved to screen_xml.py -- import via _screen_xml)
# --------------------------------------------------------------------------


def append_element(xml_text, catalog, params, theme_colors=None, golden_template_text=None):
    """Append a new element to a screen file's VisualElementList.

    Bumps UniqueIdGenerator and LastUsedIdForIdentifier, assigns a
    GenElemInst_N identifier, enforces bounds, and assigns a sequential
    VisualElementId. Returns (new_xml, geometry, info).
    """
    size_x, size_y = _screen_xml.read_screen_size(xml_text)
    owning_guid = _screen_xml.read_owning_guid(xml_text)

    # Count existing elements for sequential VisualElementId.
    existing = _screen_xml.list_elements(xml_text)
    visual_element_id = len(existing)

    last_used = _screen_xml.read_int_member(xml_text, "LastUsedIdForIdentifier")
    unique_id = _screen_xml.read_int_member(xml_text, "UniqueIdGenerator")
    next_id = last_used + 1
    identifier = "GenElemInst_{0}".format(next_id)
    identification_guid = "{0:08x}-0000-4000-8000-000000000000".format(
        next_id & 0xFFFFFFFF
    )

    golden_tmpl_name = catalog.get("golden_template")
    if golden_tmpl_name:
        if golden_template_text is not None:
            template = golden_template_text
        else:
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

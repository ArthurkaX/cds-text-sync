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

# Member block element type guid (every VisualElemMemberList entry).
_MEMBER_TYPE = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}"
_COLOR_TYPE = "{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}"
_FONT_TYPE = "{9e842eb2-1463-4af2-b605-4fbb17044f94}"
_ROOT_TYPE = "{6198ad31-4b98-445c-927f-3258a0e82fe3}"

# Indentation matching the template / ground-truth file.
_EL = " " * 12  # the <Single Type="{f86c2928...}"> element block indent
_MB = " " * 16  # member block indent inside VisualElemMemberList


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

    x = int(params.get("x")) if params.get("x") is not None else _geo_default(geo.get("x"))
    y = int(params.get("y")) if params.get("y") is not None else _geo_default(geo.get("y"))
    w = int(params.get("width")) if params.get("width") is not None else _geo_default(geo.get("width"))
    h = int(params.get("height")) if params.get("height") is not None else _geo_default(geo.get("height"))

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
                    params["shape"], ", ".join(sorted(catalog.get("shape_variants", {})))
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
        errors.append(
            "X+Width ({0}) exceeds screen SizeX ({1})".format(x + w, size_x)
        )
    if y + h > size_y:
        errors.append(
            "Y+Height ({0}) exceeds screen SizeY ({1})".format(y + h, size_y)
        )
    return errors


def render_element(catalog, params, identifier, owning_guid, identification_guid):
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
        '{el}  <Single Name="VisualElementId" Type="int">0</Single>\n'
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
        ver=catalog.get("elementVersion", 1),
    )
    return block, geometry


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
):
    """Render a new (empty) screen XML file as text."""
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
    mlist = None
    for el in element.iter():
        if _strip_ns(el.tag) == "List" and el.attrib.get("Name") == "VisualElemMemberList":
            mlist = el
            break
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
                    "color": (color_el.text or "").strip() if color_el is not None else "",
                    "canonical_name": (cn_el.text or "") if cn_el is not None else "",
                }
            else:
                out[mid] = {"kind": "list", "value": None}
    return out


def append_element(xml_text, catalog, params):
    """Append a new element to a screen file's VisualElementList.

    Bumps UniqueIdGenerator and LastUsedIdForIdentifier, assigns a
    GenElemInst_N identifier, enforces bounds. Returns (new_xml, geometry, info).
    """
    size_x, size_y = read_screen_size(xml_text)
    owning_guid = read_owning_guid(xml_text)

    last_used = _read_int_member(xml_text, "LastUsedIdForIdentifier")
    unique_id = _read_int_member(xml_text, "UniqueIdGenerator")
    next_id = last_used + 1
    identifier = "GenElemInst_{0}".format(next_id)
    identification_guid = "{0:08x}-0000-4000-8000-000000000000".format(next_id & 0xFFFFFFFF)

    block, geometry = render_element(
        catalog, params, identifier, owning_guid, identification_guid
    )

    bound_errors = validate_bounds(geometry, size_x, size_y)
    if bound_errors:
        raise BuilderError("; ".join(bound_errors))

    # Insert the block just before the closing </List> of VisualElementList.
    marker = '<List Name="VisualElementList" Type="{ef9d0b20-c96e-48db-b361-2ded4063150e}">'
    start = xml_text.find(marker)
    if start < 0:
        raise BuilderError("Screen file has no VisualElementList")
    close = xml_text.find("</List>", start)
    if close < 0:
        raise BuilderError("Malformed VisualElementList (no closing tag)")
    new_xml = xml_text[:close] + block + xml_text[close:]

    # Bump counters.
    new_xml = _replace_int_member(new_xml, "LastUsedIdForIdentifier", next_id)
    new_xml = _replace_int_member(new_xml, "UniqueIdGenerator", unique_id + 1, as_string=True)

    info = {
        "identifier": identifier,
        "type": catalog["type"],
        "geometry": geometry,
    }
    return new_xml, geometry, info


def _replace_int_member(xml_text, name, value, as_string=False):
    if as_string:
        pattern = r'(<Single Name="{0}" Type="string">)[^<]*(</Single>)'.format(re.escape(name))
    else:
        pattern = r'(<Single Name="{0}" Type="int">)[^<]*(</Single>)'.format(re.escape(name))
    repl = r"\g<1>{0}\g<2>".format(value)
    return re.sub(pattern, repl, xml_text, count=1)

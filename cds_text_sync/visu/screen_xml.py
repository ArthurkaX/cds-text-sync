# -*- coding: utf-8 -*-
"""
screen_xml.py - CODESYS visualization screen file operations.

This module holds screen-level read/update operations that were extracted
from ``builder.py`` to keep element rendering separate from screen file
management.  It uses the same text-faithful editing approach (no full
ElementTree reserialization) that ``builder.py`` uses.

Usage::

    from cds_text_sync.visu import screen_xml

    size_x, size_y = screen_xml.read_screen_size(xml_text)
    xml_text = screen_xml.resize_screen(xml_text, 1024, 600)
    xml_text = screen_xml.set_screen_background(xml_text, "#1e1e1e")
    guid = screen_xml.read_owning_guid(xml_text)
    elements = screen_xml.list_elements(xml_text)
"""

from __future__ import print_function

import re
import xml.etree.ElementTree as ET

from .xml_ns import find_named, named_text, strip_ns

# Screen root type guid (used for sibling discovery but defined here
# only if/when needed; builder.py owns the _ROOT_TYPE constant).
_SCREEN_TYPE = "{6198ad31-4b98-445c-927f-3258a0e82fe3}"


class ScreenError(Exception):
    """Raised on invalid screen XML or unexpected structure."""

    pass


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def read_screen_size(xml_text):
    """Return ``(size_x, size_y)`` from a screen file's MetaObject.

    Raises ScreenError if the values cannot be found.
    """
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise ScreenError("Could not parse screen XML: {0}".format(exc))
    size_x = size_y = None
    for el in root.iter():
        if strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeX":
            size_x = int((el.text or "0").strip())
        elif strip_ns(el.tag) == "Single" and el.attrib.get("Name") == "SizeY":
            size_y = int((el.text or "0").strip())
    if size_x is None or size_y is None:
        raise ScreenError("Screen file has no SizeX/SizeY")
    return size_x, size_y


def read_owning_guid(xml_text):
    """Return the visu's own Guid (MetaObject.Guid).

    Falls back to a fixed placeholder guid if the real one is not found.
    """
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise ScreenError("Could not parse screen XML: {0}".format(exc))
    meta = find_named(root, "Single", "MetaObject")
    if meta is not None:
        guid = find_named(meta, "Single", "Guid")
        if guid is not None and guid.text:
            return guid.text.strip()
    return "11111111-1111-1111-1111-111111111111"


def read_int_member(xml_text, name):
    """Return the integer value of a named ``<Single Name=name>`` member."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return 0
    for el in root.iter():
        if strip_ns(el.tag) == "Single" and el.attrib.get("Name") == name:
            try:
                return int((el.text or "0").strip())
            except ValueError:
                return 0
    return 0


def list_elements(xml_text):
    """Return a list of dicts describing each element in the screen.

    Each dict has keys: ``index``, ``type``, ``name``, ``identifier``,
    ``members``, ``x``, ``y``, ``width``, ``height``, ``center_x``,
    ``center_y``.
    """
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise ScreenError("Could not parse screen XML: {0}".format(exc))
    velist = None
    for el in root.iter():
        if strip_ns(el.tag) == "List" and el.attrib.get("Name") == "VisualElementList":
            velist = el
            break
    results = []
    if velist is None:
        return results
    for idx, el in enumerate(list(velist)):
        if strip_ns(el.tag) != "Single":
            continue
        info = {
            "index": idx,
            "type": named_text(el, "VisualElementTypeName"),
            "name": named_text(el, "VisualElementName"),
            "identifier": named_text(el, "VisualElementIdentifier"),
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


_VELIST_MARKER = (
    '<List Name="VisualElementList" Type="{ef9d0b20-c96e-48db-b361-2ded4063150e}">'
)


def _visual_element_list_body(xml_text):
    """Return ``(start, end)`` of the VisualElementList's contents.

    ``start`` is just past the opening tag and ``end`` is at its matching
    ``</List>``, so ``xml_text[start:end]`` is exactly the elements. Nested
    lists (a member list inside an element) are walked over by depth, and
    self-closing ``<List ... />`` does not open one.
    """
    start = xml_text.find(_VELIST_MARKER)
    if start < 0:
        raise ScreenError("Screen file has no VisualElementList")
    pos = start + len(_VELIST_MARKER)
    depth = 0
    while True:
        next_open = xml_text.find("<List", pos)
        next_close = xml_text.find("</List>", pos)
        if next_close < 0:
            raise ScreenError("Malformed VisualElementList (no closing tag)")
        if 0 <= next_open < next_close:
            tag_end = xml_text.find(">", next_open)
            if tag_end >= 0 and xml_text[tag_end - 1 : tag_end + 1] != "/>":
                depth += 1
            pos = next_open + 5
        elif depth == 0:
            return start + len(_VELIST_MARKER), next_close
        else:
            depth -= 1
            pos = next_close + 6


def clear_elements(xml_text):
    """Drop every element from the screen, keeping the screen itself.

    ``from-svg`` recompiles a whole sketch, so the sketch is the screen: what
    the author deleted from the SVG has to leave the screen too. Appending onto
    what was already there meant a second run produced a screen with both
    copies -- 31 elements became 62, overlapping pixel for pixel -- and the
    author's own edits were buried under them.

    The identifier counters are deliberately left where they are: they only
    have to keep issuing names nothing else is using, and rewinding them would
    hand a fresh element the identifier of one CODESYS has already seen.
    """
    start, end = _visual_element_list_body(xml_text)
    return xml_text[:start] + xml_text[end:]


def _member_map(element):
    """Map member id -> {value, kind, color, canonical_name} for one element."""
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


# ---------------------------------------------------------------------------
# Write / mutate operations (text-faithful)
# ---------------------------------------------------------------------------


# Match helper: locate the first <Single Name="..." Type="...">value</Single>
# pattern for a given Name, and replace its value.
_NAME_INT_RE = re.compile(
    r'(<Single\s+Name="(?P<name>[^"]+)"\s+Type="int">)(?P<before>[^<]*)(</Single>)'
)
_NAME_BOOL_RE = re.compile(
    r'(<Single\s+Name="(?P<name>[^"]+)"\s+Type="bool">)(?P<before>[^<]*)(</Single>)'
)


def resize_screen(xml_text, width, height):
    """Return *xml_text* with SizeX and SizeY updated to *width* x *height*.

    Uses text-level substitution (``re.sub``) matching the exact XML pattern.
    Raises ScreenError if either SizeX or SizeY cannot be found.
    """
    size_x, size_y = read_screen_size(xml_text)
    if (size_x, size_y) == (width, height):
        return xml_text  # no change needed

    # Replace SizeX.
    new_text = _NAME_INT_RE.sub(
        lambda m: (
            m.group(1) + str(width) + m.group(4)
            if m.group("name") == "SizeX"
            else m.group(0)
        ),
        xml_text,
        count=1,
    )
    # Sanity: ensure it changed.
    new_size_x, _ = read_screen_size(new_text)
    if new_size_x == size_x:
        # First attempt didn't match; fall back to more targeted pattern.
        new_text = re.sub(
            r'(<Single Name="SizeX" Type="int">)\d+(</Single>)',
            r"\g<1>{0}\g<2>".format(width),
            xml_text,
        )

    new_text = _NAME_INT_RE.sub(
        lambda m: (
            m.group(1) + str(height) + m.group(4)
            if m.group("name") == "SizeY"
            else m.group(0)
        ),
        new_text,
        count=1,
    )
    _, new_size_y = read_screen_size(new_text)
    if new_size_y == size_y:
        new_text = re.sub(
            r'(<Single Name="SizeY" Type="int">)\d+(</Single>)',
            r"\g<1>{0}\g<2>".format(height),
            new_text,
        )

    return new_text


def _parse_hex_color_to_signed(hex_color):
    """Parse an ARGB hex string (``#RRGGBB``, ``0xAARRGGBB``, etc.)
    to a signed 32-bit int string.

    Returns ``(signed_int_str, was_changed)`` or ``(None, False)`` if
    the input is empty/malformed.
    """
    raw = (hex_color or "").strip()
    if not raw:
        return None
    if raw.startswith("#"):
        raw = raw[1:]
    elif raw.lower().startswith("0x"):
        raw = raw[2:]
    if not raw:
        return None
    argb = int(raw, 16)
    if len(raw) <= 6:
        argb |= 0xFF000000  # opaque
    if argb >= 0x80000000:
        signed = argb - 0x100000000
    else:
        signed = argb
    return str(signed)


def set_screen_background(xml_text, color_hex):
    """Set the screen background colour from an ARGB hex string.

    Updates BgColor to True and BgUseColor to the parsed signed int.
    Returns the modified XML text.  If *color_hex* is empty or None,
    returns *xml_text* unchanged.
    """
    signed_str = _parse_hex_color_to_signed(color_hex)
    if signed_str is None:
        return xml_text

    # Set BgColor to True.
    new_text = _NAME_BOOL_RE.sub(
        lambda m: (
            m.group(1) + "True" + m.group(4)
            if m.group("name") == "BgColor"
            else m.group(0)
        ),
        xml_text,
        count=1,
    )

    # Update BgUseColor.
    new_text = _NAME_INT_RE.sub(
        lambda m: (
            m.group(1) + signed_str + m.group(4)
            if m.group("name") == "BgUseColor"
            else m.group(0)
        ),
        new_text,
        count=1,
    )

    # Fallback: if the targeted regex didn't match, try the original simple
    # patterns used in from_svg.
    if 'Name="BgColor" Type="bool">False' in new_text:
        new_text = new_text.replace(
            '<Single Name="BgColor" Type="bool">False</Single>',
            '<Single Name="BgColor" Type="bool">True</Single>',
        )
    if 'BgUseColor" Type="int">' in new_text and signed_str not in new_text:
        new_text = re.sub(
            r'(BgUseColor" Type="int">)-?\d+(</Single>)',
            r"\g<1>{0}\g<2>".format(signed_str),
            new_text,
        )

    return new_text

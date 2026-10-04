# -*- coding: utf-8 -*-
"""
xml_ns.py - Shared XML helpers for the visu module.

These helpers exist only to de-duplicate patterns that several visu modules
repeat: namespace stripping, named-child lookup, and the
``VisualElemMemberList`` traversal every member reader used to spell out for
itself.
"""


def strip_ns(tag):
    """Strip the XML namespace prefix from a tag like ``{urn}tag`` -> ``tag``."""
    return tag.split("}")[-1] if "}" in str(tag) else tag


def find_named(parent, tag_name, name):
    """Find the first child of *parent* with *tag_name* and ``Name=name``."""
    for child in list(parent):
        if strip_ns(child.tag) == tag_name and child.attrib.get("Name") == name:
            return child
    return None


def named_text(parent, name):
    """Return the text content of a named ``<Single Name=name>`` child, or ``""``."""
    child = find_named(parent, "Single", name)
    return (child.text or "").strip() if child is not None and child.text else ""


def find_member_list(element):
    """The ``<List Name="VisualElemMemberList">`` inside *element*, or ``None``.

    A visu element holds its members in a ``<Single
    Name="VisualElemMemberList">`` wrapping the list itself; the list is what
    the per-member traversal below walks.
    """
    member_container = find_named(element, "Single", "VisualElemMemberList")
    if member_container is None:
        return None
    return find_named(member_container, "List", "VisualElemMemberList")


def iter_member_list(element):
    """Yield ``(id_text, member)`` for each usable entry of a member list.

    Only ``<Single>`` entries carrying a non-empty ``<Id>`` are yielded, in
    document order, with *id_text* the stripped id text.  Parsing that id stays
    with the caller: the readers disagree on what a malformed one means (some
    let ``int()`` raise, some skip the entry), so this keeps both behaviours.
    """
    mlist = find_member_list(element)
    if mlist is None:
        return
    for member in list(mlist):
        if strip_ns(member.tag) != "Single":
            continue
        idc = find_named(member, "Single", "Id")
        if idc is None or not idc.text:
            continue
        yield idc.text.strip(), member


def member_map(element):
    """Map member id -> {value, kind, color, canonical_name} for one element.

    Shared by ``screen_xml`` and ``builder_frame``, which used to carry a copy
    each.  Returns an empty map when the element has no member list.
    """
    out = {}
    for id_text, member in iter_member_list(element):
        mid = int(id_text)
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

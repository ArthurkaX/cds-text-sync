# -*- coding: utf-8 -*-
"""
ide_snapshot_objects.py - The project objects carried by a native XML snapshot.

``cts project compare`` asks which objects differ between the live IDE and a
snapshot. Answering that needs the snapshot's *objects*, and a native CODESYS
export does not label them: nearly every node in the file carries a Name
attribute -- property keys, list names, MetaObject fields. Collecting every
Name therefore compares property names against object names, which is why a
real 187-object project reported a common count of 1.

The objects are only the ``List2 Name="EntryList"`` entries, and each carries
its identity in a ``MetaObject`` child (Guid, Name, TypeGuid) plus the Path
array CODESYS shows in the tree.

Must be compatible with IronPython 2.7.
"""
from __future__ import print_function

from ide_xml import parse_xml_file


def _local_tag(element):
    tag = element.tag
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _normalize_guid(value):
    if not value:
        return ""
    return str(value).strip().strip("{}").lower()


def _child_by_name(element, name):
    """The direct ``Single Name="name"`` child, or None.

    Direct children only: a nested object's MetaObject must never be mistaken
    for the entry's own.
    """
    for child in element:
        if _local_tag(child) == "Single" and child.attrib.get("Name") == name:
            return child
    return None


def _entry_path(entry):
    for child in entry:
        if _local_tag(child) != "Array" or child.attrib.get("Name") != "Path":
            continue
        parts = []
        for item in child:
            text = (item.text or "").strip()
            if text:
                parts.append(text)
        return parts
    return []


def _entry_object(entry):
    meta = _child_by_name(entry, "MetaObject")
    if meta is None:
        return None
    guid_elem = _child_by_name(meta, "Guid")
    name_elem = _child_by_name(meta, "Name")
    type_elem = _child_by_name(meta, "TypeGuid")
    name = (name_elem.text or "").strip() if name_elem is not None else ""
    path = _entry_path(entry)
    guid = _normalize_guid(guid_elem.text if guid_elem is not None else None)
    type_guid = _normalize_guid(type_elem.text if type_elem is not None else None)
    if not guid and not name and not path:
        return None
    return {"guid": guid, "name": name, "type_guid": type_guid, "path": path}


def snapshot_objects(path):
    """Return ``(objects, entry_list_count)`` for the native snapshot at path.

    *objects* is a list of ``{guid, name, type_guid, path}`` dicts.
    *entry_list_count* is how many EntryList containers the file held; zero
    means this is not a native CODESYS export, which a caller must report as
    "cannot compare" rather than as "the project has no objects".
    """
    root = parse_xml_file(path).getroot()
    objects = []
    entry_lists = 0
    for element in root.iter():
        if _local_tag(element) != "List2" or element.attrib.get("Name") != "EntryList":
            continue
        entry_lists += 1
        for child in element:
            if _local_tag(child) != "Single":
                continue
            obj = _entry_object(child)
            if obj is not None:
                objects.append(obj)
    return objects, entry_lists

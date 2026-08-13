# -*- coding: utf-8 -*-
"""Shared Structured Text object enumeration for the CODESYS bridge.

These helpers are not specific to any one command: the ``fmt`` and ``fsm``
commands both need to enumerate the textual objects of a project, read their
text documents, and label them. They live here so the two operations share one
implementation instead of each carrying a private copy.

This module is IronPython 2.7 safe (no f-strings, no annotations, no
dataclasses) and must not import WinForms.
"""
from __future__ import print_function

from codesys_utils import safe_str
from ide_runtime_common import object_guid, object_name
from ide_daemon_helpers import _build_path


try:
    _UNICODE_TYPE = unicode
except NameError:
    _UNICODE_TYPE = str

try:
    _BYTE_TYPE = bytes
except NameError:
    _BYTE_TYPE = str


def repair_mojibake(text):
    """Repair an obvious UTF-8 -> Latin-1 round trip in IDE text."""
    def badness(value):
        return sum(
            1
            for char in value
            if "\x80" <= char <= "\x9f" or char in "ÃÂÐÑ"
        )

    current = text
    for _ in range(2):
        if any(ord(char) > 0xFF for char in current):
            break
        try:
            candidate = current.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if badness(candidate) >= badness(current):
            break
        current = candidate
    return current


def text_of(value):
    """Return IDE text as Unicode while repairing obvious mojibake."""
    if value is None:
        return _UNICODE_TYPE()
    if isinstance(value, _UNICODE_TYPE):
        return repair_mojibake(value)
    if isinstance(value, _BYTE_TYPE):
        try:
            return repair_mojibake(value.decode("utf-8"))
        except UnicodeDecodeError:
            return repair_mojibake(value.decode("cp1251", "replace"))
    try:
        return repair_mojibake(_UNICODE_TYPE(value))
    except Exception:
        return repair_mojibake(_UNICODE_TYPE(str(value)))


def _debug_log(message):
    """Temporary diagnostic logger for the read-error investigation.

    Prints to the CODESYS Script Engine output window so the real exception
    behind a [read error] row can be copied from the IDE. Remove once the
    read-error root cause is fixed.
    """
    print("[fmt-read-debug] " + message)


def read_document(obj, attribute):
    # The section getter itself must be treated like has_text_document treats
    # it: an object type that does not support the section raises instead of
    # returning None (GVL/DUT have no textual_implementation). A raising getter
    # means "no such section", not a read error — otherwise every such object
    # in the project shows up as [read error].
    try:
        document = getattr(obj, attribute, None)
    except Exception as error:
        _debug_log(
            "GETTER {0} on {1}: {2}".format(
                attribute, safe_str(getattr(obj, "name", type(obj).__name__)), safe_str(error)
            )
        )
        return None
    if document is None:
        return None
    try:
        value = getattr(document, "text", document)
        if callable(value):
            value = value()
        return text_of(value)
    except Exception as error:
        _debug_log(
            "READ {0} on {1} (doc={2}): {3}".format(
                attribute,
                safe_str(getattr(obj, "name", type(obj).__name__)),
                safe_str(type(document).__name__),
                safe_str(error),
            )
        )
        raise RuntimeError(
            "Could not read {0}: {1}".format(attribute, safe_str(error))
        )


def has_text_document(obj):
    """Check for a text document without reading its contents."""
    for attribute in ("textual_declaration", "textual_implementation"):
        try:
            if getattr(obj, attribute, None) is not None:
                return True
        except Exception:
            pass
    return False


def object_key(obj):
    guid = object_guid(obj)
    return "guid:" + guid if guid else "id:" + str(id(obj))


def iter_textual_objects(project):
    try:
        children = list(project.get_children(recursive=True))
    except Exception:
        children = []
    result = []
    seen = set()
    for obj in children:
        key = object_key(obj)
        if key in seen or not has_text_document(obj):
            continue
        seen.add(key)
        result.append(obj)
    return result


def selected_object(holder):
    if holder is None:
        return None
    names = (
        "get_selected_object", "get_selected_objects", "get_current_object",
        "get_current_selection", "get_active_object", "selected_object",
        "selected_objects", "current_object", "current_selection",
        "active_object", "selection",
    )
    for name in names:
        try:
            value = getattr(holder, name, None)
            if callable(value):
                value = value()
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            elif value is not None and not has_text_document(value):
                try:
                    value = list(value)[0]
                except Exception:
                    pass
            if value is None:
                continue
            for wrapper in ("object", "Object", "value", "Value"):
                candidate = getattr(value, wrapper, None)
                if candidate is not None:
                    value = candidate
                    break
            if has_text_document(value):
                return value
        except Exception:
            pass
    return None


def object_label(obj):
    name = object_name(obj) or safe_str(getattr(obj, "name", ""))
    name = name or "Structured Text object"
    path = _build_path(obj)
    return path if path and path.endswith("/" + name) else name


def build_items(project, projects_obj, system):
    objects = iter_textual_objects(project)
    selected = selected_object(project) or selected_object(projects_obj) or selected_object(system)
    if selected is not None and all(
        object_key(selected) != object_key(obj) for obj in objects
    ):
        objects.insert(0, selected)

    items = []
    for obj in objects:
        label = object_label(obj)
        items.append({
            "object": obj,
            "label": label,
            "display": label,
            "status": None,
            "analysis": None,
        })
    selected_index = -1
    if selected is not None:
        for index, item in enumerate(items):
            if object_key(item["object"]) == object_key(selected):
                selected_index = index
                break
    if selected_index < 0 and items:
        selected_index = 0
    return items, selected_index

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


def _builtin(name, default):
    """Look up a builtin by name without tripping py3 NameError lints."""
    builtins = __builtins__
    if isinstance(builtins, dict):
        return builtins.get(name, default)
    return getattr(builtins, name, default)


# ``unicode`` exists only on IronPython 2.7; ``bytes`` is ``str`` there and
# the real bytes type on CPython 3.  Resolving through ``__builtins__`` keeps
# the shim free of NameError and of py3-only syntax.
_UNICODE_TYPE = _builtin("unicode", str)
_BYTE_TYPE = _builtin("bytes", str)


def _as_unicode(value):
    """Coerce *value* to the host's Unicode type without py3-only calls."""
    if isinstance(value, _UNICODE_TYPE):
        return value
    if isinstance(value, _BYTE_TYPE):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("cp1251", "replace")
    try:
        return _UNICODE_TYPE(value)
    except Exception:
        return _UNICODE_TYPE(str(value))


def repair_mojibake(text):
    """Repair an obvious UTF-8 -> Latin-1 round trip in IDE text."""

    def badness(value):
        return sum(1 for char in value if "\x80" <= char <= "\x9f" or char in "ÃÂÐÑ")

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
    return repair_mojibake(_as_unicode(value))


def read_document(obj, attribute):
    # The section getter itself must be treated like has_text_document treats
    # it: an object type that does not support the section raises instead of
    # returning None (GVL/DUT have no textual_implementation). A raising getter
    # means "no such section", not a read error — otherwise every such object
    # in the project shows up as [read error].
    try:
        document = getattr(obj, attribute, None)
    except Exception:
        return None
    if document is None:
        return None
    try:
        value = getattr(document, "text", document)
        if callable(value):
            value = value()
        return text_of(value)
    except Exception as error:
        raise RuntimeError("Could not read {0}: {1}".format(attribute, safe_str(error)))


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
        "get_selected_object",
        "get_selected_objects",
        "get_current_object",
        "get_current_selection",
        "get_active_object",
        "selected_object",
        "selected_objects",
        "current_object",
        "current_selection",
        "active_object",
        "selection",
    )
    for name in names:
        try:
            value = getattr(holder, name, None)
            if callable(value):
                value = value()
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            elif value is not None and not has_text_document(value):
                # A selection may surface as an arbitrary collection; take
                # its first element only when it is iterable and not a string.
                if not isinstance(value, (_UNICODE_TYPE, _BYTE_TYPE)):
                    try:
                        iterator = getattr(value, "__iter__", None)
                        if iterator is not None:
                            first = iterator()
                            value = first[0] if first else None
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
    selected = (
        selected_object(project)
        or selected_object(projects_obj)
        or selected_object(system)
    )
    if selected is not None and all(
        object_key(selected) != object_key(obj) for obj in objects
    ):
        objects.insert(0, selected)

    items = []
    for obj in objects:
        label = object_label(obj)
        items.append(
            {
                "object": obj,
                "label": label,
                "display": label,
                "status": None,
                "analysis": None,
            }
        )
    selected_index = -1
    if selected is not None:
        for index, item in enumerate(items):
            if object_key(item["object"]) == object_key(selected):
                selected_index = index
                break
    if selected_index < 0 and items:
        selected_index = 0
    return items, selected_index


def discover_items(project, projects_obj, system, diagnostics=None):
    """Explicit, cheap project discovery for the FMT session.

    Resolves the currently selected object first and inserts it immediately,
    then enumerates project children without reading declaration or
    implementation text.  Only stable identifier and label metadata is built;
    identifiers and labels are cached for the lifetime of the session via
    :func:`object_key`/:func:`object_label` (the path cache in
    ``ide_daemon_state``).  Opening the picker performs zero ST document
    reads; selecting one item reads only that item.

    *diagnostics* is an optional list that receives bounded summary entries
    (elapsed time and discovered editable-object count, never source text).
    """
    import time as _time

    started = _time.time()
    objects = iter_textual_objects(project)
    selected = (
        selected_object(project)
        or selected_object(projects_obj)
        or selected_object(system)
    )
    if selected is not None and all(
        object_key(selected) != object_key(obj) for obj in objects
    ):
        objects.insert(0, selected)

    items = []
    for obj in objects:
        label = object_label(obj)
        items.append(
            {
                "object": obj,
                "key": object_key(obj),
                "label": label,
                "display": label,
                "status": None,
                "analysis": None,
            }
        )
    selected_index = -1
    if selected is not None:
        for index, item in enumerate(items):
            if item["key"] == object_key(selected):
                selected_index = index
                break
    if selected_index < 0 and items:
        selected_index = 0

    if diagnostics is not None:
        diagnostics.append(
            "discovery: {0} editable object(s) in {1:.3f}s".format(
                len(items), _time.time() - started
            )
        )
    return items, selected_index

# -*- coding: utf-8 -*-
"""Local Structured Text formatting for the CODESYS ``Project_fmt`` command."""
from __future__ import print_function

from codesys_runtime import resolve_runtime
from codesys_utils import resolve_projects, safe_str
from ide_runtime_common import object_guid, object_name
from ide_daemon_helpers import _build_path
from ide_handlers_sync import _replace_text_document
from cts_shared.st.formatting import (
    format_declarations as _format_declarations,
    format_implementation as _format_implementation,
)

try:
    import codesys_fmt_ui
except Exception:
    codesys_fmt_ui = None


try:
    _UNICODE_TYPE = unicode
except NameError:
    _UNICODE_TYPE = str

try:
    _BYTE_TYPE = bytes
except NameError:
    _BYTE_TYPE = str


def _text(value):
    """Return text without changing its encoding or line endings."""
    if value is None:
        return _UNICODE_TYPE()
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


def format_text(text, declaration=False):
    """Format one pure text section using the shared analyzer core."""
    return _format_declarations(text) if declaration else _format_implementation(text)


def _read_document(obj, attribute):
    document = getattr(obj, attribute, None)
    if document is None:
        return None
    try:
        value = getattr(document, "text", document)
        if callable(value):
            value = value()
        return _text(value)
    except Exception as error:
        raise RuntimeError(
            "Could not read {0}: {1}".format(attribute, safe_str(error))
        )


def _has_text_document(obj):
    """Check for a text document without reading its contents."""
    for attribute in ("textual_declaration", "textual_implementation"):
        try:
            if getattr(obj, attribute, None) is not None:
                return True
        except Exception:
            pass
    return False


def _object_key(obj):
    guid = object_guid(obj)
    return "guid:" + guid if guid else "id:" + str(id(obj))


def _iter_textual_objects(project):
    try:
        children = list(project.get_children(recursive=True))
    except Exception:
        children = []
    result = []
    seen = set()
    for obj in children:
        key = _object_key(obj)
        if key in seen or not _has_text_document(obj):
            continue
        seen.add(key)
        result.append(obj)
    return result


def _selected_object(holder):
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
            elif value is not None and not _has_text_document(value):
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
            if _has_text_document(value):
                return value
        except Exception:
            pass
    return None


def _object_label(obj):
    name = object_name(obj) or safe_str(getattr(obj, "name", ""))
    name = name or "Structured Text object"
    path = _build_path(obj)
    return path if path and path.endswith("/" + name) else name


def _changed_lines(before, after):
    left = before.split("\n")
    right = after.split("\n")
    return sum(
        1
        for index in range(max(len(left), len(right)))
        if (left[index] if index < len(left) else "")
        != (right[index] if index < len(right) else "")
    )


def _prepare_item(obj):
    before_parts = []
    after_parts = []
    writes = []
    for attribute, is_declaration in (
        ("textual_declaration", True),
        ("textual_implementation", False),
    ):
        before = _read_document(obj, attribute)
        if before is None:
            continue
        after = format_text(before, declaration=is_declaration)
        before_parts.append(before)
        after_parts.append(after)
        writes.append((attribute, before, after))
    if not writes:
        return None

    # A synthetic source comment here made the preview look as if the IDE had
    # inserted it. Blank lines are enough to separate declaration/body panes.
    separator = "\n\n"
    before_all = separator.join(before_parts)
    after_all = separator.join(after_parts)
    changed = sum(_changed_lines(before, after) for _attr, before, after in writes)
    label = _object_label(obj)
    return {
        "object": obj,
        "label": label,
        "display": label,
        "before": before_all,
        "after": after_all,
        "writes": writes,
        "changed_lines": changed,
    }


def _analyze_item(item):
    """Read and format one object, updating its list row in place."""
    try:
        prepared = _prepare_item(item["object"])
    except Exception as error:
        item["status"] = "error"
        item["display"] = item["label"] + "    [read error]"
        item["analysis"] = "error"
        item["error"] = safe_str(error)
        return item
    if prepared is None:
        item["status"] = "error"
        item["display"] = item["label"] + "    [not editable]"
        item["analysis"] = "error"
        return item
    item.update(prepared)
    item["status"] = "changed" if item["changed_lines"] else "ok"
    item["analysis"] = "done"
    item["display"] = (
        item["label"] + "    [{0} line(s) to fix]".format(item["changed_lines"])
        if item["changed_lines"]
        else item["label"] + "    [OK]"
    )
    return item


def _apply_item(item):
    """Apply one preview atomically, refusing stale sections."""
    errors = []
    applied = []
    target = item["object"]
    for attribute, before, after in item["writes"]:
        try:
            document = getattr(target, attribute, None)
            if _read_document(target, attribute) != before:
                errors.append(attribute + " changed after analysis; preview it again")
                continue
            if not _replace_text_document(document, after):
                errors.append(attribute)
            else:
                applied.append((document, before))
        except Exception as error:
            errors.append(attribute + ": " + safe_str(error))
    if errors:
        # Do not leave a multi-section object half formatted if one write fails.
        for document, original in reversed(applied):
            try:
                _replace_text_document(document, original)
            except Exception:
                pass
        return "Could not update: " + ", ".join(errors)
    return ""


def _build_items(project, projects_obj, system):
    objects = _iter_textual_objects(project)
    selected = _selected_object(project) or _selected_object(projects_obj) or _selected_object(system)
    if selected is not None and all(
        _object_key(selected) != _object_key(obj) for obj in objects
    ):
        objects.insert(0, selected)

    items = []
    for obj in objects:
        label = _object_label(obj)
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
            if _object_key(item["object"]) == _object_key(selected):
                selected_index = index
                break
    if selected_index < 0 and items:
        selected_index = 0
    return items, selected_index


def _show_preview(item, position=None, total=None, progress=None):
    label = item["label"]
    if position is not None and total is not None:
        label = "{0}   [{1}/{2}]".format(label, position, total)
    elif position is not None:
        progress = progress or {}
        label = "{0}   [object {1}; applied {2}, skipped {3}]".format(
            label, position, progress.get("applied", 0), progress.get("skipped", 0)
        )
    if codesys_fmt_ui:
        return codesys_fmt_ui.show_fmt_preview(
            label, item["before"], item["after"], item["changed_lines"]
        )
    return "stop"


def _scan_next_changed(items, start_index):
    """Analyze objects from top to bottom until the first changed one."""
    for index in range(max(0, start_index), len(items)):
        item = items[index]
        if item.get("analysis") is None:
            _analyze_item(item)
        if item.get("status") == "changed":
            return index
    return -1


def main(params=None, runtime=None):
    params = params or {}
    if params.get("text") is not None:
        text = _text(params.get("text"))
        after = format_text(text, declaration=bool(params.get("declaration")))
        return {
            "status": "success",
            "before": text,
            "after": after,
            "changed_lines": _changed_lines(text, after),
        }

    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    if codesys_fmt_ui is None:
        message = (
            "FMT requires the CODESYS WinForms UI; non-interactive text mode "
            "accepts params.text."
        )
        runtime.ui.error(message)
        return {"status": "error", "error": message}
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    if projects_obj is None or not projects_obj.primary:
        runtime.ui.error("No open CODESYS project was found.")
        return {"status": "error", "error": "No open project"}

    project = projects_obj.primary
    items, selected_index = _build_items(project, projects_obj, runtime.system)
    if not items:
        runtime.ui.warning("No editable Structured Text objects were found in the project.")
        return {"status": "cancelled"}

    def analyze_selected(index):
        if 0 <= index < len(items):
            return _analyze_item(items[index])
        return None

    def scan_from(index):
        return _scan_next_changed(items, index)

    action, selected_index = codesys_fmt_ui.show_object_picker(
        items, selected_index, analyze_selected, scan_from
    )
    if action == "cancel":
        return {"status": "cancelled"}
    if action == "selected":
        if selected_index < 0 or selected_index >= len(items):
            return {"status": "cancelled"}
        item = items[selected_index]
        if item.get("analysis") is None:
            _analyze_item(item)
        if item.get("status") == "error":
            runtime.ui.warning("The selected object could not be read as editable Structured Text.")
            return {"status": "error", "error": item.get("error", "No editable text")}
        if not item.get("changed_lines", 0):
            runtime.ui.info("No formatting changes are needed for '" + item["label"] + "'.")
            return {"status": "unchanged", "object": item["label"]}
        if _show_preview(item) != "apply":
            return {"status": "cancelled", "object": item["label"]}
        error = _apply_item(item)
        if error:
            codesys_fmt_ui.show_message("FMT", error, "error")
            return {"status": "error", "error": error}
        codesys_fmt_ui.show_message("FMT", "Formatting applied to '" + item["label"] + "'.", "info")
        return {"status": "success", "object": item["label"], "changed_lines": item["changed_lines"]}

    current_index = selected_index
    if current_index < 0 or current_index >= len(items) or items[current_index].get("status") != "changed":
        current_index = _scan_next_changed(items, 0)
    if current_index < 0:
        runtime.ui.info("No formatting changes are needed in the project.")
        return {"status": "unchanged", "changed_objects": 0}

    applied_count = 0
    skipped_count = 0
    position = 0
    while current_index >= 0:
        position += 1
        item = items[current_index]
        preview_action = _show_preview(
            item,
            position,
            progress={"applied": applied_count, "skipped": skipped_count},
        )
        if preview_action == "stop":
            codesys_fmt_ui.show_message(
                "FMT",
                "Wizard cancelled. Applied: {0}; skipped: {1}.".format(
                    applied_count, skipped_count
                ),
                "warning",
            )
            return {
                "status": "cancelled",
                "applied": applied_count,
                "skipped": skipped_count,
                "total": position,
            }
        if preview_action == "skip":
            skipped_count += 1
        else:
            error = _apply_item(item)
            if error:
                codesys_fmt_ui.show_message("FMT", item["label"] + ": " + error, "error")
                return {"status": "error", "error": error, "applied": applied_count}
            applied_count += 1
        current_index = _scan_next_changed(items, current_index + 1)

    codesys_fmt_ui.show_message(
        "FMT",
        "Wizard complete. Applied: {0}; skipped: {1}.".format(
            applied_count, skipped_count
        ),
        "info",
    )
    return {
        "status": "success",
        "applied": applied_count,
        "skipped": skipped_count,
        "total": position,
    }

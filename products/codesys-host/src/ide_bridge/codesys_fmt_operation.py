# -*- coding: utf-8 -*-
"""Local Structured Text formatting for the CODESYS ``Project_fmt`` command."""
from __future__ import print_function

from codesys_runtime import resolve_runtime
from codesys_utils import resolve_projects, safe_str
from ide_handlers_sync import _replace_text_document
from cts_shared.st.formatting import (
    format_declarations as _format_declarations,
    format_implementation as _format_implementation,
)
from ide_st_objects import (
    build_items as _build_items,
    has_text_document as _has_text_document,
    iter_textual_objects as _iter_textual_objects,
    object_key as _object_key,
    object_label as _object_label,
    read_document as _read_document,
    repair_mojibake as _repair_mojibake,
    selected_object as _selected_object,
    text_of as _text,
)

try:
    import codesys_fmt_ui
except Exception:
    codesys_fmt_ui = None


def format_text(text, declaration=False):
    """Format one pure text section using the shared analyzer core."""
    return _format_declarations(text) if declaration else _format_implementation(text)


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
    read_errors = []
    for attribute, is_declaration in (
        ("textual_declaration", True),
        ("textual_implementation", False),
    ):
        # One unreadable section must not discard the section that did read —
        # a graphical implementation still has a Structured Text declaration
        # worth formatting.
        try:
            before = _read_document(obj, attribute)
        except Exception as error:
            read_errors.append(safe_str(error))
            continue
        if before is None:
            continue
        after = format_text(before, declaration=is_declaration)
        before_parts.append(before)
        after_parts.append(after)
        writes.append((attribute, before, after))
    if not writes:
        if read_errors:
            raise RuntimeError("; ".join(read_errors))
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
        "read_errors": read_errors,
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
        item["error"] = "CODESYS did not expose a readable Structured Text section."
        return item
    item.update(prepared)
    item["status"] = "changed" if item["changed_lines"] else "ok"
    item["analysis"] = "done"
    if item.get("read_errors"):
        suffix = (
            "[{0} line(s) to fix, partial]".format(item["changed_lines"])
            if item["changed_lines"]
            else "[OK, partial]"
        )
        item["error"] = "; ".join(item["read_errors"])
        item["suffix"] = suffix
    else:
        item["suffix"] = None
        suffix = (
            "[{0} line(s) to fix]".format(item["changed_lines"])
            if item["changed_lines"]
            else "[OK]"
        )
    item["display"] = item["label"] + "    " + suffix
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


def _mark_item_applied(item):
    """Update picker state without rereading a CODESYS object wrapper.

    Some IDE versions invalidate the document wrapper immediately after a
    successful write.  The preview already holds the exact text that was
    applied, so rereading only to paint ``[OK]`` can turn a valid apply into a
    misleading "could not be read" row.
    """
    item["before"] = item["after"]
    item["writes"] = [
        (attribute, after, after)
        for attribute, _before, after in item.get("writes", [])
    ]
    item["changed_lines"] = 0
    item["status"] = "ok"
    item["analysis"] = "done"
    item["suffix"] = None
    item["display"] = item["label"] + "    [OK]"
    return item


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
            label,
            item["before"],
            item["after"],
            item["changed_lines"],
            wizard_mode=position is not None,
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

    while True:
        action, selected_index = codesys_fmt_ui.show_object_picker(
            items, selected_index, analyze_selected, scan_from
        )
        if action == "cancel":
            return {"status": "cancelled"}
        if action != "selected":
            break
        if selected_index < 0 or selected_index >= len(items):
            return {"status": "cancelled"}
        item = items[selected_index]
        if item.get("analysis") is None:
            _analyze_item(item)
        if item.get("status") == "error":
            runtime.ui.warning("The selected object could not be read as editable Structured Text.")
            continue
        if not item.get("changed_lines", 0):
            runtime.ui.info("No formatting changes are needed for '" + item["label"] + "'.")
            continue
        if _show_preview(item) != "apply":
            # Closing a one-object preview is navigation, not cancellation of
            # Project_fmt. Reopen the picker with the same selection.
            continue
        error = _apply_item(item)
        if error:
            codesys_fmt_ui.show_message("FMT", error, "error")
            continue
        codesys_fmt_ui.show_message("FMT", "Formatting applied to '" + item["label"] + "'.", "info")
        # Keep the chooser open after a one-object apply as well. Do not read
        # the CODESYS object again here: some IDE wrappers become stale after
        # writing, while the preview already tells us the applied result.
        _mark_item_applied(item)
        continue

    current_index = selected_index
    if current_index < 0 or current_index >= len(items) or items[current_index].get("status") != "changed":
        current_index = _scan_next_changed(items, 0)
    if current_index < 0:
        runtime.ui.info("No formatting changes are needed in the project.")
        return {"status": "unchanged", "changed_objects": 0}

    state = {
        "current_index": current_index,
        "applied": 0,
        "skipped": 0,
        "position": 1,
    }

    def preview_for_current():
        item = items[state["current_index"]]
        return {
            "object_name": "{0}   [object {1}; applied {2}, skipped {3}]".format(
                item["label"], state["position"], state["applied"], state["skipped"]
            ),
            "before": item["before"],
            "after": item["after"],
            "changed_lines": item["changed_lines"],
        }

    def advance_wizard(action):
        item = items[state["current_index"]]
        if action == "skip":
            state["skipped"] += 1
        else:
            error = _apply_item(item)
            if error:
                codesys_fmt_ui.show_message("FMT", item["label"] + ": " + error, "error")
                return {"error": error}
            state["applied"] += 1
        state["current_index"] = _scan_next_changed(
            items, state["current_index"] + 1
        )
        if state["current_index"] < 0:
            return {"complete": True}
        state["position"] += 1
        return {"next": preview_for_current()}

    preview_action = codesys_fmt_ui.show_fmt_wizard(
        preview_for_current(), advance_wizard
    )
    if preview_action != "complete":
        codesys_fmt_ui.show_message(
            "FMT",
            "Wizard cancelled. Applied: {0}; skipped: {1}.".format(
                state["applied"], state["skipped"]
            ),
            "warning",
        )
        return {
            "status": "cancelled",
            "applied": state["applied"],
            "skipped": state["skipped"],
            "total": state["position"],
        }

    codesys_fmt_ui.show_message(
        "FMT",
        "Wizard complete. Applied: {0}; skipped: {1}.".format(
            state["applied"], state["skipped"]
        ),
        "info",
    )
    return {
        "status": "success",
        "applied": state["applied"],
        "skipped": state["skipped"],
        "total": state["position"],
    }

# -*- coding: utf-8 -*-
"""Local FSM diagram for the CODESYS ``Project_fsm`` command.

Read-only: this operation never writes to any project object. It scans a
selected Structured Text object for CASE state machines and shows them in a
diagram window. There is no apply path, no wizard, no rollback.
"""
from __future__ import print_function

from codesys_runtime import resolve_runtime
from codesys_utils import resolve_projects, safe_str
from ide_st_objects import (
    build_items,
    read_document,
    object_label,
    text_of,
)
from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_mermaid import to_mermaid

try:
    import codesys_fsm_ui
except Exception:
    codesys_fsm_ui = None

try:
    import codesys_fmt_ui
except Exception:
    codesys_fmt_ui = None


def _analyze_item(item):
    """Read one object and find its state machines, updating its row in place."""
    try:
        text = read_document(item["object"], "textual_implementation")
    except Exception as error:
        item["status"] = "error"
        item["suffix"] = "[read error]"
        item["analysis"] = "error"
        item["error"] = safe_str(error)
        return item
    if text is None:
        item["status"] = "ok"
        item["suffix"] = "[no FSM]"
        item["analysis"] = "done"
        item["machines"] = []
        return item
    machines = [m for m in find_machines(text) if m.is_fsm]
    item["machines"] = machines
    count = len(machines)
    if count:
        item["status"] = "changed"
        item["suffix"] = "[{0} FSM]".format(count)
    else:
        item["status"] = "ok"
        item["suffix"] = "[no FSM]"
    item["analysis"] = "done"
    return item


def _scan_next_fsm(items, start_index, visible_indexes=None):
    """Analyze objects from top to bottom until the first one with an FSM."""
    indexes = visible_indexes if visible_indexes is not None else range(len(items))
    for index in list(indexes)[max(0, start_index):]:
        item = items[index]
        if item.get("analysis") is None:
            _analyze_item(item)
        if item.get("status") == "changed":
            return index
    return -1


def _machine_payload(machine):
    return {
        "selector": machine.selector,
        "states": [state.label for state in machine.states],
        "deferred": machine.deferred,
        "numeric": machine.numeric,
        "transitions": [
            {
                "source": t.source,
                "target": t.target,
                "guard": t.guard,
                "offset": t.offset,
                "deferred": t.deferred,
            }
            for t in machine.transitions
        ],
        "warnings": [[offset, message] for offset, message in machine.warnings],
    }


def main(params=None, runtime=None):
    params = params or {}
    if params.get("text") is not None:
        text = text_of(params.get("text"))
        machines = find_machines(text)
        return {
            "status": "success",
            "machines": [_machine_payload(m) for m in machines if m.is_fsm],
            "mermaid": [to_mermaid(m) for m in machines if m.is_fsm],
        }

    runtime = resolve_runtime(runtime, caller_globals=globals(), params=params)
    if codesys_fsm_ui is None:
        message = (
            "FSM requires the CODESYS WinForms UI; non-interactive text mode "
            "accepts params.text."
        )
        runtime.ui.error(message)
        return {"status": "error", "error": message}
    projects_obj = resolve_projects(runtime.projects, runtime.caller_globals)
    if projects_obj is None or not projects_obj.primary:
        runtime.ui.error("No open CODESYS project was found.")
        return {"status": "error", "error": "No open project"}

    project = projects_obj.primary
    items, selected_index = build_items(project, projects_obj, runtime.system)
    if not items:
        runtime.ui.warning("No editable Structured Text objects were found in the project.")
        return {"status": "cancelled"}

    labels = {
        "title": "FSM - Select object",
        "heading": "Select an object to see its state machine",
        "subtitle": "Select a block to scan it for a CASE state machine. Find next FSM scans from the top and opens the first object that has one.",
        "status": "Select a block to scan it.",
        "scan_button": "Find next FSM",
        "open_button": "Show diagram",
        "scan_status": "Scanning blocks from the top...",
        "scan_none": "No state machine was found in this project.",
        "message_title": "FSM",
        "require_search": True,
        "search_prompt": "Enter a search term and press Enter first.",
    }

    def analyze_selected(index):
        if 0 <= index < len(items):
            return _analyze_item(items[index])
        return None

    def scan_from(index, visible_indexes=None):
        return _scan_next_fsm(items, index, visible_indexes)

    action, selected_index = codesys_fmt_ui.show_object_picker(
        items, selected_index, analyze_selected, scan_from, labels=labels
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
            runtime.ui.warning("The selected object could not be read as Structured Text.")
            return {"status": "error", "error": item.get("error", "No editable text")}
        machines = item.get("machines") or []
        if not machines:
            runtime.ui.info("No state machine was found in '" + item["label"] + "'.")
            return {"status": "unchanged", "object": item["label"]}
        codesys_fsm_ui.show_fsm_diagram(item["label"], machines)
        return {"status": "success", "object": item["label"], "machines": len(machines)}

    # action == "all": the picker already scanned to the first object with an FSM.
    if selected_index < 0 or selected_index >= len(items):
        return {"status": "cancelled"}
    item = items[selected_index]
    machines = item.get("machines") or []
    if not machines:
        runtime.ui.info("No state machine was found in the project.")
        return {"status": "unchanged", "changed_objects": 0}
    codesys_fsm_ui.show_fsm_diagram(item["label"], machines)
    return {"status": "success", "object": item["label"], "machines": len(machines)}

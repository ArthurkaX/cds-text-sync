# -*- coding: utf-8 -*-
"""Local FSM diagram for the CODESYS ``Project_fsm`` command.

Read-only: this operation never writes to any project object. It scans a
selected Structured Text object for CASE state machines and shows them in a
diagram window. There is no apply path, no wizard, no rollback.
"""
from __future__ import print_function

import json
import os
import subprocess
import tempfile
import time

from codesys_runtime import resolve_runtime
from codesys_utils import resolve_projects, safe_str
from ide_st_objects import (
    build_items,
    read_document,
    object_label,
    text_of,
)
from ide_st_text import split_st_text
from cts_shared.st.fsm import find_machines
from cts_shared.st.fsm_mermaid import to_mermaid

try:
    from codesys_analyze_ui_launcher import (
        _body_root,
        _project_sync_folder,
        _python_command,
    )
except Exception:
    _body_root = None
    _project_sync_folder = None
    _python_command = None

try:
    import codesys_fsm_ui
except Exception:
    codesys_fsm_ui = None

try:
    import codesys_fsm_picker
except Exception:
    codesys_fsm_picker = None

FSM_SEARCH_TIMEOUT_SECONDS = 120
MAX_SEARCH_DIAGNOSTIC = 4000
SNAPSHOT_FRESH_SECONDS = 300


class FsmSearchError(RuntimeError):
    pass


def _close_quietly(handle):
    if handle is None:
        return
    try:
        os.close(handle)
    except Exception:
        pass


def _remove_quietly(path):
    try:
        os.remove(path)
    except Exception:
        pass


def _read_utf8(path):
    """Read a child's captured stream. Project paths are frequently Cyrillic."""
    try:
        stream = open(path, "rb")
    except Exception:
        return ""
    try:
        data = stream.read()
    finally:
        stream.close()
    try:
        return data.decode("utf-8", "replace")
    except Exception:
        return safe_str(data)


def _utf8_environment():
    """Force the child to emit UTF-8 rather than the legacy Windows codepage."""
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _workspace_block_text(sync_folder, relative_path):
    """Read one exported project-view block. These paths are often Cyrillic."""
    path = os.path.join(sync_folder, "project-view",
                        relative_path.replace("/", os.sep))
    stream = open(path, "rb")
    try:
        data = stream.read()
    finally:
        stream.close()
    return data.decode("utf-8", "replace")


def _analyze_workspace_item(item, sync_folder):
    """Parse one exported block in place, in this process.

    Runs in-process because the picker analyzes one block per timer tick.
    """
    try:
        text = _workspace_block_text(sync_folder, item["label"])
    except Exception as error:
        item["machines"] = []
        item["error"] = safe_str(error)
        item["status"] = "error"
        item["suffix"] = "[read error]"
        item["analysis"] = "error"
        item["display"] = item["label"] + "    " + item["suffix"]
        return item
    _declaration, implementation = split_st_text(text)
    # split_st_text returns an empty implementation for a marker-less file,
    # where the whole blob is the body.
    machines = [m for m in find_machines(implementation or text) if m.is_fsm]
    item["machines"] = machines
    item["error"] = None
    item["status"] = "changed" if machines else "ok"
    item["suffix"] = "[{0} FSM]".format(len(machines)) if machines else "[no FSM]"
    item["analysis"] = "done"
    item["display"] = item["label"] + "    " + item["suffix"]
    return item


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


def _search_workspace(project, query, list_only=False, selected_path=None,
                      stop_at_first=False):
    if _project_sync_folder is None:
        raise FsmSearchError("CPython FSM search launcher is unavailable")
    sync_folder, error = _project_sync_folder(project)
    if error:
        raise FsmSearchError(error)
    command = [
        _python_command(), "-m", "cds_text_sync.fsm_search",
        "--workspace", sync_folder, "--query", query,
    ]
    if list_only:
        command.append("--list-only")
    if stop_at_first:
        command.append("--stop-at-first")
    if selected_path:
        command.extend(["--selected-path", selected_path])
    out_fd, out_path = tempfile.mkstemp(prefix="cts-fsm-search-", suffix=".json")
    err_fd, err_path = tempfile.mkstemp(prefix="cts-fsm-search-", suffix=".log")
    kwargs = {
        "cwd": _body_root(),
        "stdout": out_fd,
        "stderr": err_fd,
        "env": _utf8_environment(),
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        try:
            process = subprocess.Popen(command, **kwargs)
        except Exception as error:
            raise FsmSearchError("Could not start CPython FSM search: " + safe_str(error))
        deadline = time.time() + FSM_SEARCH_TIMEOUT_SECONDS
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        timed_out = process.poll() is None
        if timed_out:
            try:
                process.kill()
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass
            try:
                process.wait()
            except Exception:
                pass
        # Release our own handles before reading, so the captured text is
        # complete and the files can be removed on every exit path.
        _close_quietly(out_fd)
        _close_quietly(err_fd)
        out_fd = err_fd = None
        if timed_out:
            raise FsmSearchError(
                "FSM search timed out after {0} seconds.".format(
                    FSM_SEARCH_TIMEOUT_SECONDS))
        if process.returncode:
            detail = _read_utf8(err_path) or "CPython FSM search failed"
            raise FsmSearchError(detail[-MAX_SEARCH_DIAGNOSTIC:])
        stdout = _read_utf8(out_path)
    finally:
        _close_quietly(out_fd)
        _close_quietly(err_fd)
        _remove_quietly(out_path)
        _remove_quietly(err_path)
    try:
        result = json.loads(stdout)
    except Exception as error:
        raise FsmSearchError("Invalid CPython FSM search response: " + safe_str(error))
    if not isinstance(result, dict) or not isinstance(result.get("results", []), list):
        raise FsmSearchError("Malformed CPython FSM search response")
    return result


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


def _parse_export_time(created):
    """Parse the manifest stamp, which folder_writer writes in local time."""
    try:
        return time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def _project_saved_after(project, exported_at):
    """True when the project file on disk is newer than the export.

    This is a one-way signal: it may only add the re-export hint, never remove
    one. An unsaved edit never touches the file, so its absence proves nothing
    about whether the snapshot still matches the project.
    """
    if project is None or exported_at is None:
        return False
    try:
        path = safe_str(getattr(project, "path", "") or "")
        # A one-second margin: the export itself runs while the IDE may still
        # be flushing, and filesystem stamps are coarse.
        return bool(path) and os.path.getmtime(path) > exported_at + 1
    except Exception:
        return False


def _plural_age(count, unit):
    return "{0} {1}{2} ago".format(count, unit, "" if count == 1 else "s")


def _describe_age(seconds):
    """Age of the export in the largest unit that still reads clearly."""
    if seconds < 90:
        return "moments ago"
    if seconds < 3600:
        return _plural_age(int(round(seconds / 60.0)), "minute")
    if seconds < 86400:
        return _plural_age(int(round(seconds / 3600.0)), "hour")
    return _plural_age(int(seconds // 86400), "day")


def _snapshot_notice(sync_folder, project=None):
    """Return (notice, error) from the export manifest, never filesystem mtime."""
    root = os.path.join(sync_folder, "project-view")
    manifest = os.path.join(sync_folder, ".dump", "manifest.json")
    if not os.path.isdir(root):
        return None, "project-view is missing. Run a fresh project export."
    try:
        with open(manifest, "r") as stream:
            payload = json.load(stream)
    except Exception as error:
        return None, "Could not read exported workspace metadata ({0}). Run a fresh project export.".format(error)
    created = payload.get("created") if isinstance(payload, dict) else None
    if not created:
        return None, "Export metadata has no snapshot timestamp. Run a fresh project export."
    hint = " Re-export the project if it has changed since then."
    exported_at = _parse_export_time(created)
    if exported_at is None:
        return "Workspace snapshot from {0}.{1}".format(created, hint), None
    age = max(0.0, time.time() - exported_at)
    if _project_saved_after(project, exported_at):
        hint = " The project has been saved since - re-export to search current text."
    elif age < SNAPSHOT_FRESH_SECONDS:
        hint = ""
    return "Workspace snapshot exported {0} ({1}).{2}".format(
        _describe_age(age), created, hint), None


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
    sync_folder, sync_error = _project_sync_folder(project) if _project_sync_folder else (None, "Sync folder is not configured.")
    if sync_error or not sync_folder:
        message = sync_error or "Sync folder is not configured. Run a fresh project export."
        runtime.ui.error(message)
        return {"status": "error", "error": message}
    snapshot_notice, snapshot_error = _snapshot_notice(sync_folder, project)
    if snapshot_error:
        runtime.ui.error(snapshot_error)
        return {"status": "error", "error": snapshot_error}
    # Do not enumerate the CODESYS object tree here.  On large projects that
    # recursive API walk is slower than the actual FSM parse and makes the
    # window look frozen before the user even supplies a search term.  The
    # offline search below uses project-view as the source of truth and adds
    # only the found item to this transient list.
    items = []
    selected_index = -1

    def analyze_selected(index):
        if 0 <= index < len(items):
            item = items[index]
            if item.get("object") is not None:
                return _analyze_item(item)
            return _analyze_workspace_item(item, sync_folder)
        return None

    def scan_from(index, visible_indexes=None, query=""):
        """List the blocks matching a path search; never parse them here.

        Analysis is the picker's job now: it walks these rows lazily, one per
        timer tick, so the window keeps repainting. Parsing the whole match set
        in this call is exactly what used to freeze the dialog.
        """
        query = (query or "").strip()
        result = _search_workspace(project, query, list_only=True)
        del items[:]
        for path in result.get("candidates", []):
            items.append({
                "label": path,
                "display": path + "    [not analyzed]",
                "object": None,
                "status": None,
                "analysis": None,
            })
        return {
            "status": "Found {0} matching block(s). Click Find next FSM to analyze them.".format(
                len(items)
            )
        }

    viewed = []

    def view_selected(index):
        """Show one block's diagram on top of the picker; the picker stays up.

        Returning False leaves the picker showing why nothing opened, so the
        user lands back on the list instead of back in the IDE.
        """
        if not (0 <= index < len(items)):
            return False
        item = items[index]
        if item.get("analysis") is None:
            analyze_selected(index)
        if item.get("status") == "error":
            return False
        machines = item.get("machines") or []
        if not machines:
            return False
        codesys_fsm_ui.show_fsm_diagram(item["label"], machines)
        viewed.append(item["label"])
        return True

    action, selected_index = codesys_fsm_picker.show_fsm_object_picker(
        items, selected_index, analyze_selected, scan_from,
        snapshot_notice=snapshot_notice, view_callback=view_selected
    )
    if viewed:
        # The diagrams were shown from inside the picker, so closing it is the
        # end of the sitting, not a cancellation.
        return {
            "status": "success",
            "object": viewed[-1],
            "objects": len(viewed),
        }
    if action == "cancel":
        return {"status": "cancelled"}
    # Fallback for a picker without a view callback: it closes on the block it
    # settled on and the diagram is shown here instead.
    if selected_index < 0 or selected_index >= len(items):
        return {"status": "cancelled"}
    item = items[selected_index]
    if item.get("analysis") is None:
        analyze_selected(selected_index)
    if item.get("status") == "error":
        runtime.ui.warning("The selected object could not be read as Structured Text.")
        return {"status": "error", "error": item.get("error", "No editable text")}
    machines = item.get("machines") or []
    if not machines:
        runtime.ui.info("No state machine was found in '" + item["label"] + "'.")
        return {"status": "unchanged", "object": item["label"]}
    codesys_fsm_ui.show_fsm_diagram(item["label"], machines)
    return {"status": "success", "object": item["label"], "machines": len(machines)}

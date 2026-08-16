"""pywebview js_api bridge for the offline FSM desktop UI.

``FsmApi`` adapts the ``fsm.scanner.Scanner`` job service to the JSON-safe
dict contract the page expects.  Every public method returns a dict and never
lets an exception escape the bridge: a failure is ``{"ok": False, "error":
"..."}``.  Nothing here reads an arbitrary filesystem path - every relative
path goes through the Scanner, which already rejects traversal - and
pywebview itself is never imported at module scope (``webui.shell`` owns the
window and the folder dialog).
"""

from __future__ import annotations

import sys

from cds_text_sync.webui import shell

from .analyzer import implementation_view
from .model import STATE_ERROR
from .render import to_mermaid_text, to_plantuml_text, to_svg
from .scanner import Scanner
from .workspace import read_source, resolve_in_root


def _find_state(payload, label):
    """The payload state row whose full label is *label*, or None."""
    for state in payload["states"]:
        if state["label"] == label:
            return state
    return None


def _find_transition(payload, index):
    """The payload transition row at *index*, or None when out of range."""
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    transitions = payload["transitions"]
    if 0 <= index < len(transitions):
        return transitions[index]
    return None


def _statement_span(text, offset):
    """The single statement starting at *offset*, up to and with its ``;``.

    The fallback for an unconditional transition, which has no arm of its own.
    A statement with no terminator (a truncated file) runs to the end of text.
    """
    end = text.find(";", offset)
    return (offset, len(text) if end < 0 else end + 1)


def _trim_block(code):
    """Drop blank edges and the common indent, keeping the code's own shape.

    The first line is measured separately: a branch body starts right after
    the ``:`` of its label, so its first line carries no indent of its own and
    would otherwise pin the common indent at zero.
    """
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    rest = [line for line in lines[1:] if line.strip()]
    indent = min((len(line) - len(line.lstrip()) for line in rest), default=0)
    out = [lines[0].strip()]
    out.extend(line[indent:] if line.strip() else "" for line in lines[1:])
    return "\n".join(out).rstrip()


class FsmApi:
    """Methods exposed to the local FSM pywebview page."""

    #: What :meth:`progress` reports when nothing is in flight.
    IDLE_PROGRESS = {"running": False, "phase": "", "done": 0, "total": 0, "detail": ""}

    def __init__(self, initial_workspace: str = ""):
        self._workspace = (initial_workspace or "").strip()
        # The Scanner is deliberately not built here: the window must open even
        # for a bad path, and ``bootstrap``/``set_workspace`` rebuild it.
        self._scanner = None
        self._progress = shell.ProgressChannel(self.IDLE_PROGRESS)

    # ------------------------------------------------------------------ setup

    def _ensure_scanner(self) -> Scanner:
        """Return the current Scanner, building one for the stored workspace."""
        if self._scanner is None:
            self._scanner = Scanner(self._workspace)
        return self._scanner

    def _record_progress(self, running, phase, done, total, detail="") -> None:
        self._progress.record({
            "running": bool(running),
            "phase": str(phase),
            "done": int(done),
            "total": int(total),
            "detail": str(detail),
        })

    # ------------------------------------------------------------------ pages

    def bootstrap(self) -> dict:
        """Build the Scanner for the stored workspace and return the index.

        The payload is ``Scanner.bootstrap()`` (workspace, source_root,
        snapshot, files) merged with ``ok``/``error``.
        """
        try:
            payload = self._ensure_scanner().bootstrap()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        payload["ok"] = True
        payload["error"] = None
        self._record_progress(
            False, "idle", 0, len(payload["files"]), f"{len(payload['files'])} file(s)"
        )
        return payload

    def choose_workspace(self) -> dict:
        """Open a native folder dialog; a cancelled dialog is ``ok=True`` with
        ``workspace=""``."""
        try:
            chosen = shell.choose_folder()
        except Exception as exc:
            return {"ok": False, "workspace": "", "error": str(exc)}
        return {"ok": True, "workspace": chosen or "", "error": None}

    def set_workspace(self, path) -> dict:
        """Point the API at a new workspace and return its bootstrap payload."""
        path = str(path or "").strip()
        if not path:
            return {"ok": False, "error": "No workspace path given."}
        old = self._scanner
        self._scanner = None
        if old is not None:
            old.close()
        self._workspace = path
        return self.bootstrap()

    def refresh_workspace(self) -> dict:
        """Re-read the index, keeping cache entries whose files did not change."""
        try:
            payload = self._ensure_scanner().refresh_workspace()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        payload["ok"] = True
        payload["error"] = None
        self._record_progress(
            False, "idle", 0, len(payload["files"]), f"{len(payload['files'])} file(s)"
        )
        return payload

    # ---------------------------------------------------------------- scanning

    def start_scan(self, paths=None) -> dict:
        """Start one background scan over *paths* (or the whole index)."""
        try:
            started = self._ensure_scanner().start_scan(paths)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        self._record_progress(
            True, "scan", 0, started["total"], f"{started['total']} file(s)"
        )
        return {
            "ok": True,
            "error": None,
            "job_id": started["job_id"],
            "total": started["total"],
        }

    def poll_scan(self, job_id, cursor=0) -> dict:
        """Snapshot of one job; ``events`` holds only events after *cursor*."""
        try:
            payload = self._ensure_scanner().poll_scan(job_id, cursor)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if payload["state"] in ("completed", "cancelled", "failed"):
            self._progress.reset()
        else:
            self._record_progress(
                True, payload["state"], payload["completed"], payload["total"],
                f"{payload['completed']}/{payload['total']} file(s)",
            )
        payload["ok"] = True
        payload["error"] = None
        return payload

    def cancel_scan(self, job_id) -> dict:
        """Cooperative cancel for one scan job."""
        try:
            payload = self._ensure_scanner().cancel_scan(job_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        ok = bool(payload.get("ok"))
        payload["ok"] = ok
        payload["error"] = None if ok else f"Scan job {job_id} is not active."
        return payload

    # ------------------------------------------------------------ single file

    def analyze_file(self, relative_path) -> dict:
        """Analyse one file ahead of the queue; the row is the section 8.2 payload.

        A successful analyse (including a file with no machine) is ``ok=True``;
        only a row whose state is ``error`` is ``ok=False``.
        """
        try:
            row = self._ensure_scanner().analyze_file(relative_path)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        row["ok"] = row["state"] != STATE_ERROR
        if not row["ok"]:
            row["error"] = row["error"] or f"Could not analyse {relative_path}"
        return row

    def render(self, relative_path, machine=0) -> dict:
        """Render one machine of one file as SVG and text, with its rows.

        ``transitions`` is the payload's transition list in payload order, and
        each row's ``index`` is the payload index, so a row matches the
        ``data-transition`` attribute ``render.to_svg`` emits.  A file with no
        machine is a successful render with ``count=0`` and empty output, NOT
        an error; an out-of-range machine index is ``ok=False``.
        """
        try:
            try:
                machine_index = int(machine)
            except (TypeError, ValueError):
                return {
                    "ok": False,
                    "error": f"Machine index is not an integer: {machine!r}",
                }
            row = self._ensure_scanner().analyze_file(relative_path)
            if row["state"] == STATE_ERROR:
                return {
                    "ok": False,
                    "error": row["error"] or f"Could not analyse {relative_path}",
                }
            machines = row["machines"]
            if not machines:
                return {
                    "ok": True,
                    "error": None,
                    "path": str(relative_path),
                    "machine": machine_index,
                    "count": 0,
                    "svg": "",
                    "mermaid": "",
                    "plantuml": "",
                    "summary": None,
                    "warnings": [],
                    "transitions": [],
                }
            if machine_index < 0 or machine_index >= len(machines):
                return {
                    "ok": False,
                    "error": (
                        f"machine index {machine_index} is out of range "
                        f"({len(machines)} machine(s) in {relative_path})"
                    ),
                }
            payload = machines[machine_index]
            return {
                "ok": True,
                "error": None,
                "path": str(relative_path),
                "machine": machine_index,
                "count": len(machines),
                "svg": to_svg(payload),
                "mermaid": to_mermaid_text(payload),
                "plantuml": to_plantuml_text(payload),
                "summary": {
                    "selector": payload["selector"],
                    "state_count": len(payload["states"]),
                    "transition_count": len(payload["transitions"]),
                    "deferred": payload["deferred"],
                    "numeric": payload["numeric"],
                },
                "warnings": payload["warnings"],
                "transitions": [
                    {
                        "index": index,
                        "source": transition["source"],
                        "target": transition["target"],
                        "guard": transition["guard"],
                        "offset": transition["offset"],
                        "lhs": transition["lhs"],
                        "deferred": transition["deferred"],
                    }
                    for index, transition in enumerate(payload["transitions"])
                ],
            }
        except Exception as exc:
            return {"ok": False, "error": f"Render failed unexpectedly: {exc}"}

    def source(self, relative_path, machine=0, kind="state", key=None) -> dict:
        """Return the ST code behind one step or one transition.

        ``kind="state"`` takes the full state label as *key* and returns the
        CASE branch body - the code the step runs. ``kind="transition"`` takes
        the payload transition index and returns the arm the transition fires
        inside, which is where its actions live; an unconditional transition
        has no arm, so the single assignment statement is returned instead and
        ``block`` is False.

        The file is re-read and re-analysed here rather than sliced from what
        the page already holds: an offset from the page could point anywhere,
        and the file may have changed since it was drawn.
        """
        try:
            try:
                machine_index = int(machine)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"Machine index is not an integer: {machine!r}"}
            kind = str(kind)
            if kind not in ("state", "transition"):
                return {"ok": False, "error": f"Unknown source kind: {kind!r}"}

            scanner = self._ensure_scanner()
            row = scanner.analyze_file(relative_path)
            if row["state"] == STATE_ERROR:
                return {
                    "ok": False,
                    "error": row["error"] or f"Could not analyse {relative_path}",
                }
            machines = row["machines"]
            if machine_index < 0 or machine_index >= len(machines):
                return {
                    "ok": False,
                    "error": (
                        f"machine index {machine_index} is out of range "
                        f"({len(machines)} machine(s) in {relative_path})"
                    ),
                }
            payload = machines[machine_index]

            resolved = resolve_in_root(scanner.source_root, str(relative_path))
            if resolved is None or not resolved.is_file():
                return {"ok": False, "error": f"Source file is unreadable: {relative_path}"}
            analysed, whole = implementation_view(read_source(resolved))

            if kind == "state":
                found = _find_state(payload, key)
                if found is None:
                    return {"ok": False, "error": f"No state named {key!r} in this machine."}
                start, end = found["start_offset"], found["end_offset"]
                header = {"title": found["label"], "subtitle": "state body", "block": True}
            else:
                found = _find_transition(payload, key)
                if found is None:
                    return {"ok": False, "error": f"No transition {key!r} in this machine."}
                start, end = found["block_start"], found["block_end"]
                block = start is not None
                if not block:
                    start, end = _statement_span(analysed, found["offset"])
                header = {
                    "title": (found["source"] or "(any)") + " → " + found["target"],
                    "subtitle": found["guard"] or "unconditional",
                    "block": block,
                }

            code = _trim_block(analysed[start:end if end is not None else len(analysed)])
            # analysed is a suffix of whole, so the offset difference is the
            # number of characters the declaration took up.
            absolute = len(whole) - len(analysed) + (start or 0)
            result = {
                "ok": True,
                "error": None,
                "path": str(relative_path),
                "machine": machine_index,
                "kind": kind,
                "code": code,
                "line": whole.count("\n", 0, absolute) + 1,
            }
            result.update(header)
            return result
        except Exception as exc:
            return {"ok": False, "error": f"Could not read the source: {exc}"}

    # ------------------------------------------------------------------ status


    def progress(self) -> dict:
        """Snapshot of the last reported status; see ``webui.shell.ProgressChannel``."""
        return self._progress.snapshot()

    def close(self) -> None:
        """Close the Scanner, if one exists; safe to call twice."""
        scanner = self._scanner
        self._scanner = None
        if scanner is not None:
            try:
                scanner.close()
            except Exception as error:  # pragma: no cover - window teardown path
                print(f"[ERROR] Failed to close FSM scanner: {error}", file=sys.stderr)

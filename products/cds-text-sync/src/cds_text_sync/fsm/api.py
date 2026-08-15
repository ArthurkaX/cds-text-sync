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

from .model import STATE_ERROR
from .render import to_mermaid_text, to_plantuml_text, to_svg
from .scanner import Scanner


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

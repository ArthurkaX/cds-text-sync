"""Reusable pywebview plumbing shared by the local desktop applications.

Nothing here is specific to any single UI: no analyzer rules, no FSM data,
only the conventions and small helpers every local webview window needs.
``pywebview`` itself is imported only inside :func:`choose_folder` and
:func:`start_window`, so importing this module never requires the optional
dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path


class ProgressChannel:
    """Lock-free progress report convention for pywebview bridges.

    pywebview dispatches every bridge call on its own thread, so the report is
    read while the worker is still writing.  The whole dict is REPLACED rather
    than mutated, so a poll sees either the previous report or the next one,
    never a half-written one, and no lock is needed on either side.
    """

    def __init__(self, idle: dict):
        # Keep our own copy so the caller's dict is never aliased.
        self._idle = dict(idle)
        self._report = dict(idle)

    def snapshot(self) -> dict:
        """Return a copy of the current report."""
        return dict(self._report)

    def record(self, payload: dict) -> None:
        """Replace the whole report wholesale."""
        self._report = dict(payload)

    def reset(self) -> None:
        """Return to the idle report."""
        self._report = dict(self._idle)


def choose_folder() -> str:
    """Open a native folder dialog and return the chosen path or ""."""
    import webview

    folders = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    return folders[0] if folders else ""


def resolve_under_root(root, relative) -> Path | None:
    """Resolve *relative* beneath *root*, or return None when it escapes.

    Both sides are ``.resolve()``d before the containment check, so ``..``
    segments and absolute paths cannot reach outside *root*.
    """
    root = Path(root).resolve()
    target = (root / str(relative or "")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def package_page(module_file, assets_dir, page: str = "index.html") -> Path:
    """Return the packaged page path next to *module_file*'s *assets_dir*."""
    return Path(module_file).with_name(assets_dir) / page


READY_LINE = "CTS-UI-READY"


def announce_ready(stream=None) -> None:
    """Print the readiness line the external launcher waits for.

    The launcher cannot tell a slow pywebview import from a crash by timing
    alone, so the child says so itself: this line is written and flushed once
    the window exists and the process is about to hand control to the event
    loop.
    """
    stream = sys.stdout if stream is None else stream
    stream.write(READY_LINE + "\n")
    stream.flush()


def start_window(
    title, page, js_api, width, height, min_size, install_hint
) -> int:
    """Create the native pywebview window, or explain the missing extra.

    Returns 0 after the window closes, or 2 with *install_hint* on stderr when
    pywebview is not installed.
    """
    try:
        import webview
    except ImportError:
        print(install_hint, file=sys.stderr)
        return 2
    webview.create_window(
        title,
        page.as_uri(),
        js_api=js_api,
        width=width,
        height=height,
        min_size=min_size,
    )
    announce_ready()
    webview.start()
    return 0

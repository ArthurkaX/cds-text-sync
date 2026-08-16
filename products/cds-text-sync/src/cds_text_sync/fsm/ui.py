"""Local desktop window for the offline FSM map.

A thin adapter over ``webui.shell`` and ``fsm.api.FsmApi``: the page path,
the native window, the folder dialog, and the optional-dependency message all
live in the shared shell.  pywebview is imported only inside
``webui.shell.start_window``, so this module stays importable without the
optional UI dependency.
"""

from __future__ import annotations

import os
from pathlib import Path

from cds_text_sync.webui import shell

from .api import FsmApi

# The assets sit at the package root next to ``ui_assets``, one level above
# this module.  ``shell.package_page(__file__, ...)`` resolves a sibling of the
# calling module, so it would point inside ``fsm/`` and the window would open
# on ERR_FILE_NOT_FOUND; anchor on the package directory instead.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def page_path() -> Path:
    """Return the packaged page this window loads."""
    return PACKAGE_ROOT / "fsm_ui_assets" / "index.html"


def _resolve_initial_workspace(initial_workspace: str = "") -> str:
    """Resolve the explicit workspace or the CODESYS launcher fallback."""
    return (
        initial_workspace
        or os.environ.get("CTS_FSM_INITIAL_WORKSPACE", "")
        or os.environ.get("CTS_INITIAL_WORKSPACE", "")
    ).strip()


def launch(initial_workspace: str = "") -> int:
    """Create the native FSM window, or explain how to install the UI extra."""
    initial_workspace = _resolve_initial_workspace(initial_workspace)
    page = page_path()
    return shell.start_window(
        "CTS FSM Map",
        page,
        js_api=FsmApi(initial_workspace),
        width=1240,
        height=780,
        min_size=(980, 640),
        install_hint=(
            "[ERROR] The desktop UI is optional. Install it with: "
            'pip install -e ".[ui]"'
        ),
    )

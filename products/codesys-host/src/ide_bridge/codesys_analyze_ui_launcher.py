# -*- coding: utf-8 -*-
"""Start the CPython/pywebview analyzer UI from a CODESYS menu entry.

This module runs under the CODESYS IronPython ScriptEngine, but it deliberately
contains no UI and imports no analyzer modules.  Its only responsibility is to
read the active project's configured sync folder and start the separate
CPython process that hosts the WebView2 window.
"""
from __future__ import print_function

from codesys_external_ui_launcher import notify, start_ui
from codesys_runtime import resolve_runtime
from codesys_utils import resolve_projects


def main(params=None, caller_globals=None):
    runtime = resolve_runtime(
        caller_globals=caller_globals, params=params, headless=False
    )
    projects = resolve_projects(runtime.projects, runtime.caller_globals)
    project = projects.primary if projects is not None else None
    if project is None:
        message = "No CODESYS project is open."
        notify(runtime, message, is_error=True)
        return {"status": "error", "error": message}
    return start_ui(runtime, project, ["ui"], "the analyzer UI")

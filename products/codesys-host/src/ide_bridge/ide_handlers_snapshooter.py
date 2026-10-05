# -*- coding: utf-8 -*-
"""
ide_handlers_snapshooter.py -- the daemon's ``snapshooter`` command.

The CODESYS menu only opens the Snapshooter dialog in front of a person
(Tools -> Scripting -> cds-text-sync -> Project_snapshooter).  This handler is
the same backend without the person: it drives project_snapshooter.py's UI-free
functions so ``cts snapshooter`` can build the variable tree, take a preset,
diff one against the live PLC, restore it (dry-run by default), or run the
dialog headlessly through project_snapshooter_ui.check.

Actions arrive as ``params["action"]``:
    tree      -- leaf variables (path, type); ``params["path"]`` filters by prefix
    take      -- a preset document; ``params["out"]`` saves it
    diff      -- compare a preset (``params["input"]`` or ``params["preset"]``)
    restore   -- same preset source; writes only when ``params["apply"]`` is true
    ui_check  -- create the dialog without showing it and drive a scripted run

Every response is ``{"ok": ..., "data": ...}`` or ``{"ok": False, "error": ...}``,
matching the neighbouring handlers.  ``params["out"]`` and ``params["input"]``
name files this process opens, so a relative one is refused outright rather
than resolved against the CODESYS working directory.  This runs in IronPython
2.7.
"""

from __future__ import print_function

import os

import project_snapshooter as backend
from cts_shared.coerce import as_bool
from ide_daemon_state import _get_active_project

_ACTIONS = ("tree", "take", "diff", "restore", "ui_check")


def _text(value):
    if value is None:
        return ""
    try:
        return unicode(value)  # noqa: F821 - IronPython
    except NameError:
        return str(value)


def _action_app(params):
    return _text(params.get("app", "")) or "Application"


def _relative_path_error(params, *names):
    """An error dict if any named file path is relative, else ``None``.

    This process runs inside CODESYS.exe, so a relative path lands in the IDE's
    installation directory -- an UnauthorizedAccessException when writing there,
    or a file nobody looks at.  The CLI absolutises these before sending them;
    answering with this message rather than a raw OS error says what actually
    went wrong for any other client.
    """
    for name in names:
        value = _text(params.get(name, ""))
        if value and not os.path.isabs(value):
            return {
                "ok": False,
                "error": "path must be absolute: {0} {1}".format(name, value),
            }
    return None


def _cmd_snapshooter(params):
    """Dispatch one ``snapshooter`` action. See the module docstring."""
    action = _text(params.get("action", ""))
    if action not in _ACTIONS:
        return {
            "ok": False,
            "error": "Unknown snapshooter action: {0}".format(action or "(none)"),
        }
    refusal = _relative_path_error(params, "out", "input")
    if refusal is not None:
        return refusal
    try:
        if action == "ui_check":
            return _snapshooter_ui_check(params)
        project, err = _get_active_project()
        if err is not None:
            return err
        app = _action_app(params)
        if action == "tree":
            return _snapshooter_tree(params, project, app)
        if action == "take":
            return _snapshooter_take(params, project, app)
        if action == "diff":
            return _snapshooter_diff(params, project, app)
        return _snapshooter_restore(params, project, app)
    except Exception as e:
        return {"ok": False, "error": "Snapshooter {0} failed: {1}".format(action, e)}


def _snapshooter_tree(params, project, app):
    prefix = _text(params.get("path", ""))
    if as_bool(params.get("refresh", False)):
        backend.invalidate_tree_cache(project)
    leaves = []
    for row in backend.build_tree(app=app, project=project):
        path = _text(row.get("path", ""))
        if prefix and not path.startswith(prefix):
            continue
        leaves.append({"path": path, "type": _text(row.get("type", ""))})
    build = backend.tree_build_info()
    return {
        "ok": True,
        "data": {
            "action": "tree",
            "app": app,
            "path": prefix or None,
            "count": len(leaves),
            "tree_source": build["source"],
            "tree_built_at": build["built_at"],
            "leaves": leaves,
        },
    }


def _snapshooter_take(params, project, app):
    paths = backend._normalize_paths(params.get("paths"))
    label = _text(params.get("label", ""))
    document = backend.take(paths=paths or None, app=app, label=label, project=project)
    data = {
        "action": "take",
        "app": app,
        "label": label,
        "count": len(backend._vars_from_data(document)),
        "document": document,
    }
    out = _text(params.get("out", ""))
    if out:
        data["saved_to"] = backend.save(document, out)
    return {"ok": True, "data": data}


def _snapshooter_preset(params):
    """The preset dict for diff/restore: inline ``preset`` or a file ``input``."""
    preset = params.get("preset")
    if isinstance(preset, dict):
        return preset
    path = _text(params.get("input", ""))
    if not path:
        raise RuntimeError("Pass --input <preset.json> or an inline preset.")
    return backend.load(path)


def _snapshooter_diff(params, project, app):
    preset = _snapshooter_preset(params)
    paths = [v.get("path", "") for v in backend._vars_from_data(preset)]
    current = backend.take(paths=paths, app=app, project=project)
    report = backend.compare(preset, current=current)
    return {
        "ok": True,
        "data": {
            "action": "diff",
            "app": app,
            "count": len(paths),
            "report": report,
        },
    }


def _snapshooter_restore(params, project, app):
    preset = _snapshooter_preset(params)
    apply = as_bool(params.get("apply", False))
    result = backend.restore(preset, apply=apply, project=project)
    return {
        "ok": True,
        "data": {
            "action": "restore",
            "app": app,
            "applied": bool(apply),
            "result": result,
        },
    }


def _snapshooter_ui_check(params):
    """Create the dialog without Show/DoEvents and run the scripted scenario.

    A failure to build the window at all (for example a session with no
    desktop) is reported as ``{"ok": False, "error": ...}``; a dialog step
    that raises is kept inside the returned report instead.
    """
    import project_snapshooter_ui

    report = project_snapshooter_ui.check(
        backend=vars(backend),
        app=_action_app(params),
        script=params.get("script"),
    )
    if not report.get("ok", False):
        return {"ok": False, "error": report.get("error", "ui_check failed")}
    return {"ok": True, "data": {"action": "ui_check", "report": report}}

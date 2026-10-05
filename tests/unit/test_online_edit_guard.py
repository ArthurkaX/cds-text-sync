# -*- coding: utf-8 -*-
"""
test_online_edit_guard.py — no project edit may run while the IDE is online.

The user's rule: a CODESYS project must not be edited while the IDE is logged
in to the PLC. ``cts import`` did exactly that live and returned exit 0: the
daemon started before the user logged in, so it had no cached online handle,
and the old preflight (``is_online_session_active``) only ever looked at that
cache. The import silently created half-applied objects, and their symbols were
never exported to the running application.

The guard therefore asks ``require_online_session`` -- the same detection the
data plane uses -- which adopts the session already online in the IDE UI
(a wrapper only, never a login). One helper answers for every project-editing
command; this module pins the helper, the detection it must use, and that the
guarded handlers refuse before touching anything.
"""

from __future__ import print_function

import importlib.machinery
import importlib.util
import os
import sys
import types
from types import SimpleNamespace

import pytest

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

STATE_KEY = "_codesys_daemon_loop"


def _load(name):
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def _clean_daemon_state():
    saved = getattr(sys, STATE_KEY, None)
    if hasattr(sys, STATE_KEY):
        delattr(sys, STATE_KEY)
    yield
    if saved is None:
        if hasattr(sys, STATE_KEY):
            delattr(sys, STATE_KEY)
    else:
        setattr(sys, STATE_KEY, saved)


# ── the helper itself ───────────────────────────────────────────────────────


def test_offline_lets_the_edit_through(monkeypatch):
    guard = _load("ide_online_guard")
    monkeypatch.setattr(guard, "_live_session", lambda project: None)
    assert guard.project_edit_refusal(object(), "sync_import_text") is None


def test_online_refuses_and_names_the_command():
    guard = _load("ide_online_guard")
    sys._codesys_daemon_loop = {"online_app": object(), "online_target_app": object()}

    refusal = guard.project_edit_refusal(object(), "update_pou")

    assert refusal["ok"] is False
    assert "cts disconnect" in refusal["error"]
    assert "editing the project while online is not supported" in refusal["error"]
    assert refusal["error"].endswith("repeat update_pou.")


# ── the bug: an IDE session the daemon never cached ─────────────────────────


def _install_adopted_ide_session(monkeypatch):
    """An IDE-online session visible only through create_online_application.

    The wrapper exposes ``application_state`` and neither ``is_connected`` nor
    ``is_online`` -- the SP22 case. ``is_online_session_active`` (cache only)
    must report offline; the guard must not.
    """
    wrapper = SimpleNamespace(application_state="run")
    monkeypatch.setitem(
        sys.modules,
        "scriptengine",
        SimpleNamespace(
            online=SimpleNamespace(create_online_application=lambda app: wrapper)
        ),
    )
    sys._codesys_daemon_loop = {}
    return SimpleNamespace(active_application=object()), wrapper


def test_the_old_cache_only_check_misses_an_adopted_ide_session(monkeypatch):
    project, _wrapper = _install_adopted_ide_session(monkeypatch)
    helpers = _load("ide_online_helpers")
    assert helpers.is_online_session_active() is False
    assert helpers.require_online_session(project) is not None


def test_an_adopted_ide_session_is_refused(monkeypatch):
    project, wrapper = _install_adopted_ide_session(monkeypatch)
    guard = _load("ide_online_guard")
    refusal = guard.project_edit_refusal(project, "sync_import_text")
    assert refusal is not None
    assert "cts disconnect" in refusal["error"]
    assert sys._codesys_daemon_loop["online_app"] is wrapper


# ── handler integration: the guard runs, and nothing is written ────────────


_STUBBED = ("ide_runtime_common", "ide_daemon_state", "ide_daemon_helpers",
            "ide_apply_patch")


def _load_sync():
    saved = dict((name, sys.modules.get(name)) for name in _STUBBED)
    try:
        for name in _STUBBED:
            sys.modules[name] = types.ModuleType(name)
        state = sys.modules["ide_daemon_state"]
        state._log = lambda *a, **k: None
        state._get_active_project = lambda: (None, None)
        state._read_text_utf8 = lambda path: ""
        helpers = sys.modules["ide_daemon_helpers"]
        for name in ("_active_application_name", "_find_object_by_selector",
                     "_find_object_in_project", "_get_sync_folder",
                     "_invalidate_device_cache"):
            setattr(helpers, name, lambda *a, **k: None)
        loader = importlib.machinery.SourceFileLoader(
            "ide_handlers_sync_online_guard_under_test",
            os.path.join(_BRIDGE, "ide_handlers_sync.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class _Project(object):
    def __init__(self):
        self.import_native_calls = []
        self.remove_calls = 0
        self.declaration = None

    def import_native(self, path):
        self.import_native_calls.append(path)

    def remove(self):
        self.remove_calls += 1


def _sync_with_refusal(monkeypatch, project):
    sync = _load_sync()
    recorded = []

    def refuse(proj, command):
        recorded.append(command)
        return {"ok": False, "error": "refused {0}".format(command)}

    monkeypatch.setattr(sync.ide_online_guard, "project_edit_refusal", refuse)
    monkeypatch.setattr(sync, "_get_active_project", lambda: (project, None))
    return sync, recorded


def test_sync_import_refuses_without_importing(monkeypatch, tmp_path):
    source = tmp_path / "IDE.xml"
    source.write_text("<Project/>")
    project = _Project()
    sync, recorded = _sync_with_refusal(monkeypatch, project)

    result = sync._cmd_sync_import({"input": str(source)})

    assert result["ok"] is False
    assert recorded == ["sync_import"]
    assert project.import_native_calls == []


def test_update_pou_refuses_before_reading_or_writing(monkeypatch, tmp_path):
    project = _Project()
    sync, recorded = _sync_with_refusal(monkeypatch, project)

    result = sync._cmd_update_pou({"name": "PRG", "st_path": str(tmp_path / "x.st")})

    assert result["ok"] is False
    assert recorded == ["update_pou"]


def test_delete_pou_refuses_without_removing(monkeypatch):
    project = _Project()
    sync, recorded = _sync_with_refusal(monkeypatch, project)

    result = sync._cmd_delete_pou({"name": "PRG"})

    assert result["ok"] is False
    assert recorded == ["delete_pou"]
    assert project.remove_calls == 0


def test_a_read_only_sync_command_does_not_ask_the_guard(monkeypatch):
    project = _Project()
    sync, recorded = _sync_with_refusal(monkeypatch, project)
    monkeypatch.setattr(sync, "_get_sync_folder", lambda: (None, "not set"))

    sync._cmd_sync_export({})

    assert recorded == []


# ── the project-editing handlers ────────────────────────────────────────────


class _Info(object):
    def __init__(self):
        self.values = {}


def _install_project(monkeypatch, values):
    info = _Info()
    info.values = values
    project = SimpleNamespace(
        info=info, get_project_info=lambda: info, save=lambda: None
    )
    monkeypatch.setitem(sys.modules, "scriptengine", SimpleNamespace())
    sys._codesys_daemon_loop = {
        "projects": SimpleNamespace(primary=project),
        "started_at": "now",
    }
    return project, info


def test_set_sync_folder_refuses_online(monkeypatch):
    handlers = _load("ide_handlers_project")
    project, info = _install_project(monkeypatch, {})
    monkeypatch.setattr(
        handlers.ide_online_guard,
        "project_edit_refusal",
        lambda proj, command: {"ok": False, "error": "refused " + command},
    )

    result = handlers._cmd_set_sync_folder({"path": "C:/sync"})

    assert result == {"ok": False, "error": "refused set_sync_folder"}
    assert info.values == {}


def test_set_simulation_mode_refuses_online(monkeypatch):
    handlers = _load("ide_handlers_project")
    _install_project(monkeypatch, {})
    monkeypatch.setattr(
        handlers.ide_online_guard,
        "project_edit_refusal",
        lambda proj, command: {"ok": False, "error": "refused " + command},
    )

    result = handlers._cmd_set_simulation_mode({"enable": "on"})

    assert result == {"ok": False, "error": "refused set_simulation_mode"}


# ── the guard must be the single source, not a copy per handler ─────────────


def _guarded_commands(relative_path, sink_name):
    """Every literal command name passed to project_edit_refusal in a file."""
    import ast

    source = open(os.path.join(_BRIDGE, relative_path), encoding="utf-8").read()
    found = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else None
        if name != sink_name or len(node.args) != 2:
            continue
        found.add(node.args[1].value)
    return found


def test_every_project_editing_command_is_guarded():
    sync = _guarded_commands("ide_handlers_sync.py", "project_edit_refusal")
    project = _guarded_commands("ide_handlers_project.py", "project_edit_refusal")
    assert sync == {"sync_import", "sync_import_text", "update_pou", "delete_pou"}
    assert project == {"set_sync_folder", "set_simulation_mode"}


def test_the_refusal_text_has_exactly_one_definition():
    guard = open(os.path.join(_BRIDGE, "ide_online_guard.py"), encoding="utf-8").read()
    assert guard.count("The IDE is online with the PLC; editing the project while") == 1

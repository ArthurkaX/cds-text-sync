# -*- coding: utf-8 -*-
"""The headless ``project_snapshooter_ui.check`` contract.

``check`` is the Snapshooter dialog without the person: it builds the same form
``run`` builds -- but never shows it or pumps messages -- then drives the
handlers on a scripted scenario and returns a structural report.  It is what
the daemon's ``snapshooter ui_check`` action calls.

The .NET surface and the backend namespace are the fakes from
``test_snapshooter_ui_run`` so both entry points are exercised against one
model of WinForms.  These tests pin what a future decomposition must keep:

* no ``Form.Show`` and no ``Application.DoEvents`` (the whole point of a
  headless run);
* every MessageBox is recorded with its title and text;
* the default scenario runs every step, and its ``Load`` step completes now
  that ``_recompute_parent_states`` no longer crashes;
* a failing step is recorded and leaves the rest of the scenario running;
* a window that cannot be built at all yields ``ok: False`` with a message.
"""

import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapshooter_ui_run import Backend, DotNet, _load_ui_module  # noqa: E402


@pytest.fixture
def ui_env(tmp_path):
    """A fresh UI module with the fake clr/WinForms modules installed."""
    dotnet = DotNet()
    saved = {}
    for name, module in dotnet.modules.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    backend = Backend(dotnet, str(tmp_path))
    # The preset Load reads back contains the leaf the scenario checked first,
    # so the report's checked-leaf count reflects a real round trip.
    backend.load_result = {"paths": ["GVL.a"]}
    ui = _load_ui_module()
    try:
        yield ui, backend, dotnet
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _check(ui_env, app="Application", script=None):
    ui, backend, _dotnet = ui_env
    return ui.check(backend.as_dict(), app=app, script=script)


def _names(report):
    return [step["name"] for step in report["steps"]]


def _event_names(dotnet):
    return [event[0] for event in dotnet.events]


# ── The default scenario ───────────────────────────────────────────────────


def test_the_default_scenario_runs_every_step(ui_env):
    report = _check(ui_env)

    assert report["ok"] is True
    assert _names(report) == list(ui_env[0]._DEFAULT_CHECK_STEPS)


def test_every_default_step_succeeds(ui_env):
    """The Load step used to report the known _recompute_parent_states crash."""
    report = _check(ui_env)

    for step in report["steps"]:
        assert step["ok"] is True, (step["name"], step["error"])
    assert report["failed_steps"] == []
    assert report["all_steps_ok"] is True


def test_failed_steps_names_every_step_that_raised(ui_env):
    ui, _backend, _dotnet = ui_env

    def boom(_state):
        raise RuntimeError("step is broken")

    ui._CHECK_STEPS["load"] = boom
    ui._CHECK_STEPS["diff"] = boom

    report = _check(ui_env)

    assert report["failed_steps"] == ["load", "diff"]
    assert report["all_steps_ok"] is False
    # ``ok`` keeps meaning "the window was built", so old callers are unaffected.
    assert report["ok"] is True


def test_the_form_is_built_but_never_shown_or_pumped(ui_env):
    _ui, _backend, dotnet = ui_env

    _check(ui_env)

    assert len(dotnet.forms) == 1
    names = _event_names(dotnet)
    assert "Form.__init__" in names
    assert "Form.Show" not in names
    assert "Application.DoEvents" not in names
    # The WinForms surface was still loaded for real.
    assert names[:2] == ["clr.AddReference", "clr.AddReference"]


def test_the_windows_shown_are_reported_with_title_and_text(ui_env):
    report = _check(ui_env)

    assert report["windows"], "the scenario shows at least the Save box"
    titles = [window["title"] for window in report["windows"]]
    # Load used to be absent here: it died before its completion box.
    assert titles == ["Save", "Load", "Diff", "Restore"]
    assert all(set(window) == {"title", "text"} for window in report["windows"])
    assert all(isinstance(window["text"], str) for window in report["windows"])


def test_the_load_step_reports_how_many_variables_it_loaded(ui_env):
    report = _check(ui_env)

    loaded = [w for w in report["windows"] if w["title"] == "Load"]
    assert loaded == [{"title": "Load", "text": "Loaded 1 variables."}]


def test_the_save_and_open_dialogs_are_reported(ui_env):
    report = _check(ui_env)

    kinds = [kind for kind, _path in report["files"]]
    assert "SaveFileDialog" in kinds
    assert "OpenFileDialog" in kinds
    assert all(os.path.basename(path) for _kind, path in report["files"])
    assert report["preset_file"] == report["files"][0][1]


def test_checked_leaves_and_parent_state_are_reported(ui_env):
    report = _check(ui_env)

    # check_first_leaf checked GVL.a and the Load round trip kept it checked.
    assert report["checked_leaves"] == 1
    assert report["leaf_count"] == 3
    assert "Application" in report["parents"]
    assert "GVL" in report["parents"]


def test_app_is_forwarded_to_the_tree_builders(ui_env):
    ui, backend, _dotnet = ui_env

    report = ui.check(backend.as_dict(), app="MyApp")

    assert report["app"] == "MyApp"
    build_calls = [e for e in backend.dotnet.events if e[0] == "build_tree"]
    assert build_calls and build_calls[0][1] == "MyApp"


# ── Scripting and failure handling ─────────────────────────────────────────


def test_a_script_overrides_the_default_steps(ui_env):
    report = _check(ui_env, script=["save", "diff"])

    assert _names(report) == ["save", "diff"]
    assert all(step["ok"] for step in report["steps"])


def test_an_unknown_step_is_recorded_not_raised(ui_env):
    report = _check(ui_env, script=["nope", "save"])

    assert report["ok"] is True
    by_name = {step["name"]: step for step in report["steps"]}
    assert by_name["nope"]["ok"] is False
    assert "unknown ui_check step: nope" in by_name["nope"]["error"]
    # The step after the bad one still ran.
    assert by_name["save"]["ok"] is True


def test_a_failing_step_does_not_stop_the_rest(ui_env):
    ui, _backend, _dotnet = ui_env

    def boom(_state):
        raise RuntimeError("step is broken")

    ui._CHECK_STEPS["load"] = boom

    report = _check(ui_env, script=["load", "diff", "restore"])

    by_name = {step["name"]: step for step in report["steps"]}
    assert by_name["load"]["ok"] is False
    assert by_name["load"]["error"] == "RuntimeError: step is broken"
    assert by_name["diff"]["ok"] is True
    assert by_name["restore"]["ok"] is True


def test_a_backend_failure_inside_a_step_is_caught(ui_env):
    """The step's own backend call failing is recorded, not raised."""
    _ui, backend, _dotnet = ui_env

    def boom(*args, **kwargs):
        raise RuntimeError("preset is unreadable")

    backend.load = boom
    backend.as_dict()["load"] = boom

    report = _check(ui_env, script=["load"])

    assert report["steps"] == [
        {"name": "load", "ok": False, "error": "RuntimeError: preset is unreadable"}
    ]


def test_restore_is_a_dry_run_when_answered_no(ui_env):
    ui, backend, dotnet = ui_env

    report = _check(ui_env, script=["restore"])

    assert report["steps"][0]["ok"] is True
    # The confirmation was shown as a Yes/No prompt and answered No, so the
    # backend's restore() was never reached.
    assert any("Write matching variables" in w["text"] for w in report["windows"])
    assert "restore" not in _event_names(dotnet)


# ── The window itself cannot be built ──────────────────────────────────────


def test_a_tree_failure_is_reported_as_not_ok(ui_env):
    _ui, backend, _dotnet = ui_env
    backend.build_tree_error = RuntimeError("Snapshooter requires project property cds-sync-folder.")

    report = _check(ui_env)

    assert report["ok"] is False
    assert "the variable tree could not be built" in report["error"]
    assert report["steps"] == []
    # Nothing ran, so nothing is known to be ok -- and nothing "failed" either.
    assert report["failed_steps"] == []
    assert report["all_steps_ok"] is False
    # The tree error box was recorded even on the failure path.
    assert any("cds-sync-folder" in w["text"] for w in report["windows"])


def test_a_project_failure_is_reported_as_not_ok(ui_env):
    _ui, backend, _dotnet = ui_env

    def no_project():
        raise RuntimeError("No active CODESYS project is available.")

    backend._get_active_project = no_project
    backend.as_dict()["_get_active_project"] = no_project

    report = _check(ui_env)

    assert report["ok"] is False
    assert "No active CODESYS project" in report["error"]


def test_the_load_box_counts_ticked_leaves_and_names_the_missing_ones(ui_env):
    """What the Load step reports when the preset names unknown paths."""
    _ui, backend, _dotnet = ui_env
    backend.load_result = {"paths": ["GVL.a", "Nope.one", "Nope.two"]}

    report = _check(ui_env, script=["load"])

    assert report["steps"][0]["ok"] is True
    assert [w for w in report["windows"] if w["title"] == "Load"] == [
        {
            "title": "Load",
            "text": "Loaded 1 variables.\n2 not found in the tree.",
        }
    ]
    assert report["checked_leaves"] == 1

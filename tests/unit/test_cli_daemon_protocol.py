# -*- coding: utf-8 -*-
"""
test_cli_daemon_protocol.py -- CLI <-> daemon method-parity contract.

Every daemon method the top-level CLI sends must be handled by the reverse-pipe
daemon. Command name, CLI->method mapping, and the daemon's handler table live in
three different files (cli/_cli_parser.py, cli/_cli_handlers_daemon.py,
src/ide_bridge/ide_reverse_pipe_loop.py); nothing enforces that they agree, so a
renamed daemon handler or a typo'd method name is a silent runtime failure
("Unknown method: X") that no unit test would otherwise catch. These contract
tests close that gap.

Scope: the ACTIVE top-level daemon command surface -- the _cli_handlers_daemon
and _cli_handlers_vars routers. The hidden/deprecated `project`/`pou` subcommands
route through _cli_io._project_command to method names that are NOT all present
in the reverse-pipe _DISPATCH (e.g. project_open, set_simulation_mode); those are
intentionally OUT OF SCOPE here -- asserting on them would couple this guard to
deprecated code whose (possibly forward-mode) daemon path is not runtime-testable
under CPython. That mismatch is a separate, pre-existing concern.

The daemon module is IronPython 2.7 but imports cleanly under CPython once .NET
namespaces are stubbed (same technique as test_daemon_name_resolution), so we
read the REAL _DISPATCH/_ALIASES/_NO_PERMISSION objects rather than parsing them.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_IDE_BRIDGE = _ROOT / "src" / "ide_bridge"
_CLI = _ROOT / "cli"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Import the IronPython daemon under .NET stubs (see test_daemon_name_resolution
# for the fuller version of this infrastructure).
# ---------------------------------------------------------------------------

_STUB_NAMES = [
    "clr",
    "System",
    "System.IO",
    "System.IO.Pipes",
    "System.Threading",
    "System.Windows",
    "System.Windows.Forms",
    "System.Drawing",
    "System.Collections",
    "System.Collections.Generic",
    "System.Array",
    "System.Byte",
    "scriptengine",
]


class _AutoStub:
    """Callable no-op that returns itself for any attribute access."""

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return _STUB_SINGLETON

    def __iter__(self):
        return iter([])


_STUB_SINGLETON = _AutoStub()


def _stub_module(name):
    mod = ModuleType(name)
    mod.__spec__ = None
    mod.__getattr__ = lambda attr: _STUB_SINGLETON  # type: ignore[attr-defined]
    return mod


def _load_daemon_module():
    """Import ide_reverse_pipe_loop under stubs and return the live module."""
    saved = {name: sys.modules.get(name) for name in _STUB_NAMES}
    for name in _STUB_NAMES:
        sys.modules[name] = _stub_module(name)

    had_loop = hasattr(sys, "_codesys_daemon_loop")
    if not had_loop:
        sys._codesys_daemon_loop = {}  # type: ignore[attr-defined]

    bridge = str(_IDE_BRIDGE)
    added_path = bridge not in sys.path
    if added_path:
        sys.path.insert(0, bridge)

    prev = sys.modules.pop("ide_reverse_pipe_loop", None)
    try:
        spec = importlib.util.spec_from_file_location(
            "ide_reverse_pipe_loop", str(_IDE_BRIDGE / "ide_reverse_pipe_loop.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["ide_reverse_pipe_loop"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        # The module is fully executed; _DISPATCH etc. are plain dicts now, so
        # tearing the stubs back down does not affect what we read from it.
        if prev is not None:
            sys.modules["ide_reverse_pipe_loop"] = prev
        else:
            sys.modules.pop("ide_reverse_pipe_loop", None)
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        if added_path:
            try:
                sys.path.remove(bridge)
            except ValueError:
                pass
        if not had_loop:
            try:
                del sys._codesys_daemon_loop  # type: ignore[attr-defined]
            except AttributeError:
                pass


@pytest.fixture(scope="module")
def daemon():
    try:
        return _load_daemon_module()
    except Exception as exc:  # pragma: no cover - import must succeed
        pytest.fail(
            "ide_reverse_pipe_loop must import under CPython stubs but raised "
            "{0}: {1}".format(type(exc).__name__, exc)
        )


def _resolvable_methods(daemon_module):
    """Method names the daemon can dispatch: _DISPATCH keys plus aliases of them."""
    dispatch = set(daemon_module._DISPATCH)
    aliases = daemon_module._ALIASES
    return dispatch | {key for key, target in aliases.items() if target in dispatch}


# ---------------------------------------------------------------------------
# AST scan: daemon method names sent as string literals by a CLI handler module.
# ---------------------------------------------------------------------------

# Functions whose FIRST positional arg is the daemon method name.
_SEND_FUNCS = {"cmd_daemon", "send_command_reverse", "_batch"}


def _sent_method_literals(py_path):
    tree = ast.parse(Path(py_path).read_text(encoding="utf-8"))
    methods = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name not in _SEND_FUNCS:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            methods.add(first.value)
    return methods


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_daemon_methods_table_is_dispatchable(daemon):
    """Every value in _cli_handlers_daemon._DAEMON_METHODS is a daemon handler."""
    from cli._cli_handlers_daemon import _DAEMON_METHODS

    resolvable = _resolvable_methods(daemon)
    missing = {cmd: m for cmd, m in _DAEMON_METHODS.items() if m not in resolvable}
    assert not missing, (
        "CLI commands map to daemon methods with no handler in _DISPATCH: "
        + ", ".join("{0}->{1}".format(c, m) for c, m in sorted(missing.items()))
    )


def test_direct_sends_are_dispatchable(daemon):
    """Every literal daemon method sent by the daemon/vars handlers is handled."""
    resolvable = _resolvable_methods(daemon)
    sent = set()
    for handler_file in ("_cli_handlers_daemon.py", "_cli_handlers_vars.py"):
        sent |= _sent_method_literals(_CLI / handler_file)
    # Sanity: the scan actually found sends (guards against a silent no-match).
    assert "read_variables" in sent and "cicd" in sent, sorted(sent)
    missing = sorted(m for m in sent if m not in resolvable)
    assert not missing, (
        "CLI handlers send daemon methods with no handler in _DISPATCH: "
        + ", ".join(missing)
    )


def test_no_permission_entries_are_real_methods(daemon):
    """Daemon-internal invariant: every _NO_PERMISSION name is a real handler.

    A _NO_PERMISSION entry for a method not in _DISPATCH is dead (it exempts a
    command that can never run) and usually signals a rename that missed one
    side.
    """
    dispatch = set(daemon._DISPATCH)
    unknown = sorted(m for m in daemon._NO_PERMISSION if m not in dispatch)
    assert not unknown, (
        "_NO_PERMISSION lists names absent from _DISPATCH: " + ", ".join(unknown)
    )


# ---------------------------------------------------------------------------
# Characterization of a KNOWN DEFECT (not a passing contract).
#
# The hidden/deprecated `project` subcommand routes every action through
# _cli_io._project_command, which ALWAYS sends over the reverse pipe (its
# `use_reverse` parameter is dead -- the body never branches on it). Several
# actions send daemon methods that have no handler in _DISPATCH, so at runtime
# they return {"ok": false, "error": "Unknown method: X"}. The daemon has a
# single static dispatch table (Project_daemon.py only exec()s the reverse-pipe
# loop -- there is no forward mode), so these commands are genuinely broken:
#
#   cts project open / close / list / list-devices / simulate /
#   set-credentials / diagnose-online      (+ top-level `cts discover`)
#
# This test pins the EXACT broken set so the defect is visible and bounded:
#   * fix one (add the daemon handler) -> this test fails, prompting its removal
#     from _KNOWN_UNHANDLED;
#   * add a new broken _project_command send -> this test fails.
# Fixing it for real (add IronPython handlers, or remove the dead actions) is a
# user-facing call tracked separately; it is not asserted as passing here.
# ---------------------------------------------------------------------------

_KNOWN_UNHANDLED = frozenset(
    {
        "project_open",
        "project_close",
        "project_list",
        "list_devices",
        "set_simulation_mode",
        "set_credentials",
        "diagnose_online",
        "discover",
    }
)


def test_project_subcommand_unhandled_set_is_exactly_known(daemon):
    """The `project` handlers' unhandled daemon methods are exactly the known set."""
    resolvable = _resolvable_methods(daemon)
    project_sends = set()
    for node in ast.walk(
        ast.parse(
            (_CLI / "_cli_handlers_project.py").read_text(encoding="utf-8")
        )
    ):
        if (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.func, ast.Name)
            and node.func.id == "_project_command"
        ):
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                project_sends.add(first.value)

    unhandled = {m for m in project_sends if m not in resolvable}
    assert unhandled == set(_KNOWN_UNHANDLED), (
        "project-subcommand broken-method set drifted.\n"
        "  newly broken (add handler or update set): "
        + ", ".join(sorted(unhandled - set(_KNOWN_UNHANDLED)))
        + "\n  now fixed (remove from _KNOWN_UNHANDLED): "
        + ", ".join(sorted(set(_KNOWN_UNHANDLED) - unhandled))
    )


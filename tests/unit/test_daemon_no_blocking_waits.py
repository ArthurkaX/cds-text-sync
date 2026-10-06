# -*- coding: utf-8 -*-
"""
test_daemon_no_blocking_waits.py — the daemon's tick path must not sleep.

The daemon now runs on a WinForms timer inside the IDE's message loop. Every
call on that path runs on the UI thread, so a ``time.sleep`` there freezes the
IDE -- the freeze this design removes. This is a static check, in the same
spirit as the login-call-site check added in t30: a *new* blocking wait fails
the test until someone consciously adds it to the list below with a reason,
rather than shipping quietly.

The allow-list is deliberately tiny and each entry is bounded:

  * ``_cicd_cold_reset`` -- one deliberate settle after a cold reset, before
    the PLC is logged into again. Part of an explicit, already-long reset.
  * ``_run_test_plan`` -- a ``wait`` step the user wrote into the test plan. It
    is the plan asking for the wait, not the daemon inventing one.
  * ``atomic_write`` -- a short bounded retry when antivirus holds the target
    file; the .NET File.Replace path above it is the normal one.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_IDE_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"

#: Every module that runs on the daemon's tick thread.
_SCANNED = [
    "ide_reverse_pipe_loop.py",
    "codesys_daemon_launcher.py",
    "ide_daemon_state.py",
    "ide_online_helpers.py",
] + sorted(p.name for p in _IDE_BRIDGE.glob("ide_handlers_*.py"))

#: (file, enclosing function) pairs where a sleep is allowed, with the reason
#: in the module docstring. Anything else is a blocking wait on the UI thread.
_ALLOWED_SLEEPS = {
    ("ide_handlers_cicd.py", "_cicd_cold_reset"),
    ("ide_handlers_cicd.py", "_run_test_plan"),
    ("ide_online_helpers.py", "atomic_write"),
}


class _QualNames(ast.NodeVisitor):
    """Map every call node to the chain of function names around it."""

    def __init__(self):
        self.stack = []
        self.calls = []

    def visit_FunctionDef(self, node):  # noqa: N802 - ast API
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node):  # noqa: N802 - ast API
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node):  # noqa: N802 - ast API
        self.calls.append((node, list(self.stack)))
        self.generic_visit(node)


def _sleep_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    qualifier = _QualNames()
    qualifier.visit(tree)
    found = []
    for node, stack in qualifier.calls:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "sleep":
            found.append(stack[0] if stack else "<module>")
    return found


def _doevents_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    qualifier = _QualNames()
    qualifier.visit(tree)
    found = []
    for node, stack in qualifier.calls:
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name in ("DoEvents", "pump_events"):
            found.append(stack[0] if stack else "<module>")
    return found


def test_only_the_allow_listed_sleeps_remain_on_the_tick_path():
    found = set()
    for name in _SCANNED:
        path = _IDE_BRIDGE / name
        for function in _sleep_calls(path):
            found.add((name, function))

    unexpected = found - _ALLOWED_SLEEPS
    assert not unexpected, (
        "a new blocking wait appeared on the daemon tick path; it runs on the "
        "IDE's UI thread. Remove it, shorten it, move it to the client, or add "
        "it to _ALLOWED_SLEEPS with a reason: {0}".format(sorted(unexpected))
    )
    # The allow-list must not rot: an entry that no longer exists is a lie.
    stale = _ALLOWED_SLEEPS - found
    assert not stale, "allow-listed waits that no longer exist: {0}".format(
        sorted(stale)
    )


def test_the_tick_does_not_pump_events():
    """Application.DoEvents inside a tick can deliver a nested tick or a Stop."""
    offenders = {}
    for name in _SCANNED:
        calls = _doevents_calls(_IDE_BRIDGE / name)
        if calls:
            offenders[name] = calls

    assert not offenders, (
        "DoEvents/pump_events must not run on the tick path: {0}".format(offenders)
    )


def test_the_launcher_does_not_hold_the_script_open():
    """A keep-alive loop in the launcher is what pinned the IDE in
    "Executing script ... CANCEL" for the daemon's whole lifetime."""
    path = _IDE_BRIDGE / "codesys_daemon_launcher.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            while_loops = [n for n in ast.walk(node) if isinstance(n, ast.While)]
            assert not while_loops, (
                "codesys_daemon_launcher.run must start the timer and return; "
                "a while loop there re-creates the frozen IDE"
            )
            return
    raise AssertionError("codesys_daemon_launcher.run not found")


def test_the_loop_module_starts_a_timer_and_returns():
    """The entry point must not contain a service loop of its own."""
    path = _IDE_BRIDGE / "ide_reverse_pipe_loop.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_loop":
            while_loops = [n for n in ast.walk(node) if isinstance(n, ast.While)]
            assert not while_loops, "run_loop must not loop: the timer does that"
            return
    raise AssertionError("run_loop not found")

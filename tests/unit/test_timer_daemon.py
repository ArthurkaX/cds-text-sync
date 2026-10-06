# -*- coding: utf-8 -*-
"""
test_timer_daemon.py — the WinForms-timer service model (the 1.x method).

The daemon used to run a ``while running:`` loop inside the CODESYS script, so
the IDE sat in "Executing script ... CANCEL" for the daemon's whole lifetime.
It now creates a WinForms timer and returns; the IDE's own message loop drives
the ticks. These tests pin the parts that make that safe:

  * starting creates exactly one timer, armed, and returns;
  * the tick interval comes from the configured ``poll_ms``;
  * a nested tick (the timer fires while its handler runs, or a UI handler
    pumps messages) does nothing at all;
  * an error inside the tick is logged and the timer is re-armed, so one bad
    command cannot kill the daemon;
  * a stop is honoured whether it arrives between ticks (Stop button) or from
    inside the tick (``stop_daemon``), and the timer is disposed, never left
    running next to a new one;
  * running Project_daemon.py again is the start/stop toggle.

The CODESYS/CLR surface is stubbed exactly as test_daemon_handshake does it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parent.parent.parent
_IDE_BRIDGE = _ROOT / "products" / "codesys-host" / "src" / "ide_bridge"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self

    def __iter__(self):
        return iter([])


def _stub_module(name):
    mod = ModuleType(name)
    mod.__spec__ = None
    mod.__getattr__ = lambda attr: _AutoStub()  # type: ignore[attr-defined]
    return mod


def _load_loop():
    """Import the loop module with clr/System stubbed, as CODESYS would."""
    saved = {}
    for name in _STUB_NAMES:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = _stub_module(name)
    if str(_IDE_BRIDGE) not in sys.path:
        sys.path.insert(0, str(_IDE_BRIDGE))
    sys.modules.pop("ide_reverse_pipe_loop", None)
    try:
        return importlib.import_module("ide_reverse_pipe_loop")
    finally:
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig


rpl = _load_loop()


class _Event:
    """A .NET-style event: ``timer.Tick += handler`` works on it."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        while handler in self.handlers:
            self.handlers.remove(handler)
        return self


class FakeTimer:
    def __init__(self):
        self.Interval = 0
        self.Tick = _Event()
        self.starts = 0
        self.stops = 0
        self.disposals = 0
        self.running = False

    def Start(self):
        self.starts += 1
        self.running = True

    def Stop(self):
        self.stops += 1
        self.running = False

    def Dispose(self):
        self.disposals += 1


class _NoClientPipe:
    """What the poll sees when no CLI is waiting: a refused connection."""

    def __init__(self, *args, **kwargs):
        pass

    def Connect(self, timeout_ms):
        raise RuntimeError("Could not connect to pipe")

    def Close(self):
        pass


def _fresh_state():
    sys._codesys_daemon_loop = {
        "running": None,
        "started": False,
        "projects": None,
        "system": None,
        "command_count": 0,
        "last_command": None,
        "online_app": None,
        "online_target_app": None,
        "timeout_profile": None,
        "config": {"poll_ms": 200},
    }


def _install(monkeypatch, timers):
    """Common fixtures: a timer factory, no CLI waiting, silent I/O."""
    def _make():
        timer = FakeTimer()
        timers.append(timer)
        return timer

    monkeypatch.setattr(rpl, "_make_timer", _make)
    monkeypatch.setattr(rpl, "_log_startup", lambda: None)
    monkeypatch.setattr(rpl, "_log", lambda *_a, **_k: None)
    monkeypatch.setattr(rpl, "write_daemon_status", lambda *_a, **_k: None)
    monkeypatch.setattr(rpl, "clear_daemon_status", lambda *_a, **_k: None)
    monkeypatch.setattr(rpl, "NamedPipeClientStream", _NoClientPipe)


def test_starting_creates_exactly_one_armed_timer_and_returns(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()

    rpl.start_daemon()

    assert len(timers) == 1
    timer = timers[0]
    assert sys._codesys_daemon_loop["timer"] is timer
    assert timer.Interval == 200
    assert timer.running is True
    assert timer.starts == 1
    assert sys._codesys_daemon_loop["started"] is True
    assert sys._codesys_daemon_loop["running"] is True


def test_the_tick_interval_comes_from_poll_ms(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    sys._codesys_daemon_loop["config"] = {"poll_ms": 500}

    rpl.start_daemon()

    assert timers[0].Interval == 500


def test_starting_disposes_a_stale_timer_before_arming_a_new_one(monkeypatch):
    """Two live timers would poll the same pipe twice and fight over it."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    stale = FakeTimer()
    sys._codesys_daemon_loop["timer"] = stale

    rpl._ensure_timer()

    assert stale.disposals == 1
    assert stale.running is False
    assert sys._codesys_daemon_loop["timer"] is timers[0]
    assert sys._codesys_daemon_loop["timer"] is not stale


def test_running_the_script_again_stops_the_daemon(monkeypatch):
    """Project_daemon.py is the start/stop toggle, as in 1.x."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    rpl.start_daemon()
    timer = timers[0]

    rpl.run_loop()

    assert timer.disposals == 1
    assert timer.running is False
    assert sys._codesys_daemon_loop["timer"] is None
    assert sys._codesys_daemon_loop["running"] is False


def test_running_the_script_again_after_a_stop_starts_a_new_daemon(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()

    rpl.run_loop()
    assert len(timers) == 1
    rpl.run_loop()  # toggle off
    rpl.run_loop()  # toggle on again

    assert len(timers) == 2
    assert sys._codesys_daemon_loop["timer"] is timers[1]
    assert timers[1].running is True


def test_a_nested_tick_does_nothing(monkeypatch):
    """The timer fires while its handler runs; the second tick must be a no-op.

    A nested tick would re-enter the CODESYS API from under the running
    command, which is exactly what the single-threaded engine cannot take.
    """
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    served = []

    def _serve():
        served.append(1)
        rpl._on_tick(None, None)  # the re-entrant tick
        return False

    monkeypatch.setattr(rpl, "_service_one_client", _serve)
    rpl.start_daemon()

    rpl._on_tick(None, None)

    assert served == [1]
    assert sys._codesys_daemon_loop[rpl._TICK_BUSY_KEY] is False
    assert timers[0].running is True


def test_a_tick_skips_while_a_ui_handler_is_running(monkeypatch):
    """The dashboard's Run Tests button pumps messages while it works."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    served = []
    monkeypatch.setattr(
        rpl, "_serve_connection", lambda pipe, dash=None: served.append(1) or False
    )
    rpl.start_daemon()
    sys._codesys_daemon_loop["ui_busy"] = True

    rpl._on_tick(None, None)

    assert served == []


def test_an_error_in_the_tick_keeps_the_timer_armed(monkeypatch):
    """One bad command must not kill the daemon."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()

    def _boom(pipe, dash=None):
        raise RuntimeError("tick blew up")

    monkeypatch.setattr(rpl, "_serve_connection", _boom)
    monkeypatch.setattr(rpl, "_service_one_client", _boom)
    rpl.start_daemon()
    timer = timers[0]
    starts_before = timer.starts

    rpl._on_tick(None, None)

    assert timer.starts == starts_before + 1
    assert timer.running is True
    assert sys._codesys_daemon_loop["running"] is True
    assert sys._codesys_daemon_loop[rpl._TICK_BUSY_KEY] is False


def test_a_stop_from_inside_the_tick_disposes_the_timer(monkeypatch):
    """``cts stop`` (stop_daemon) is served inside the tick."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    monkeypatch.setattr(rpl, "_service_one_client", lambda: True)
    rpl.start_daemon()
    timer = timers[0]
    starts_before = timer.starts

    rpl._on_tick(None, None)

    assert timer.disposals == 1
    assert timer.running is False
    # Not re-armed: the shutdown happened, it did not silently continue.
    assert timer.starts == starts_before
    assert sys._codesys_daemon_loop["timer"] is None
    assert sys._codesys_daemon_loop["running"] is False


def test_a_stop_between_ticks_is_honoured_on_the_next_tick(monkeypatch):
    """The Stop button only clears ``running``; the next tick tears down."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    served = []
    monkeypatch.setattr(
        rpl, "_serve_connection", lambda pipe, dash=None: served.append(1) or False
    )
    rpl.start_daemon()
    timer = timers[0]
    sys._codesys_daemon_loop["running"] = False

    rpl._on_tick(None, None)

    assert served == []
    assert timer.disposals == 1
    assert timer.running is False
    assert sys._codesys_daemon_loop["timer"] is None


def test_shutdown_clears_the_liveness_marker_and_closes_the_dashboard(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    cleared = []
    closed = []
    monkeypatch.setattr(rpl, "clear_daemon_status", lambda: cleared.append(1))
    monkeypatch.setattr(
        rpl,
        "_ui",
        type("UI", (), {"show_daemon_ui": staticmethod(lambda: None),
                        "pump_events": staticmethod(lambda form: None)}),
    )
    dash = type("Dash", (), {"close_window": lambda self: closed.append(1)})()
    sys._codesys_daemon_loop["dashboard"] = dash

    rpl._request_shutdown()
    rpl._request_shutdown()  # idempotent

    assert cleared == [1]
    assert closed == [1]


def test_no_cli_waiting_is_not_an_error(monkeypatch):
    """An empty pipe is the normal case: the tick returns and re-arms."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    logged = []
    monkeypatch.setattr(rpl, "_log", lambda msg: logged.append(msg))
    rpl.start_daemon()
    timer = timers[0]
    sys._codesys_daemon_loop["_heartbeat_ts"] = 0.0

    rpl._on_tick(None, None)

    assert timer.running is True
    assert not any("Pipe poll error" in line for line in logged)


def test_the_first_read_of_a_connection_is_bounded(monkeypatch):
    """A client that connects and sends nothing must not hold the UI thread."""
    applied = []

    class _Pipe:
        def __init__(self, *args, **kwargs):
            pass

        def Connect(self, timeout_ms):
            pass

        @property
        def ReadTimeout(self):
            return 0

        @ReadTimeout.setter
        def ReadTimeout(self, value):
            applied.append(value)

        def Close(self):
            pass

    monkeypatch.setattr(rpl, "NamedPipeClientStream", _Pipe)
    monkeypatch.setattr(rpl, "_serve_connection", lambda pipe, dash=None: False)

    rpl._service_one_client()

    assert applied == [rpl.READ_TIMEOUT_MS]
    assert rpl.READ_TIMEOUT_MS > 0


def test_the_poll_connect_does_not_wait(monkeypatch):
    """Connect(0) is one immediate attempt in .NET; anything > 0 blocks the UI
    thread for that long on every tick, and -1 would block forever."""
    waits = []

    class _Pipe:
        def __init__(self, *args, **kwargs):
            pass

        def Connect(self, timeout_ms):
            waits.append(timeout_ms)
            raise RuntimeError("Could not connect to pipe")

        def Close(self):
            pass

    monkeypatch.setattr(rpl, "NamedPipeClientStream", _Pipe)

    assert rpl._service_one_client() is False
    assert waits == [rpl.CONNECT_TIMEOUT_MS]
    assert rpl.CONNECT_TIMEOUT_MS == 0


# ── One daemon per pipe: the AppDomain anchor and the named mutex ─────────
#
# Every Execute Script gets a fresh IronPython runtime, so a daemon that kept
# its state in ``sys`` was invisible to the next run of Project_daemon.py --
# three runs, three daemons.  The state now lives in the AppDomain (see
# ide_daemon_anchor) and a named mutex covers a second CODESYS process.


class FakeMutex:
    def __init__(self):
        self.released = 0
        self.closed = 0

    def ReleaseMutex(self):
        self.released += 1

    def Close(self):
        self.closed += 1


def test_a_second_start_asks_and_starts_nothing_when_declined(monkeypatch):
    """Answering "No" to the confirm dialog leaves the running daemon alone."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    monkeypatch.setattr(rpl, "_confirm_stop_running_daemon", lambda state: False)
    rpl.start_daemon()
    timer = timers[0]
    starts_before = timer.starts

    rpl.run_loop()

    assert len(timers) == 1  # no competitor was created
    assert timer.disposals == 0
    assert timer.running is True
    assert timer.starts == starts_before
    assert sys._codesys_daemon_loop["timer"] is timer


def test_a_second_start_stops_the_daemon_when_confirmed(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    monkeypatch.setattr(rpl, "_confirm_stop_running_daemon", lambda state: True)
    rpl.start_daemon()
    timer = timers[0]

    rpl.run_loop()

    assert timer.disposals == 1
    assert sys._codesys_daemon_loop["timer"] is None


def test_the_confirm_text_names_the_running_daemon(monkeypatch):
    """The dialog says which pid and since when, so the user can decide."""
    shown = []

    class _MessageBox:
        @staticmethod
        def Show(message, caption, buttons):
            shown.append(message)
            return "yes"

    class _Result:
        Yes = "yes"

    class _Buttons:
        YesNo = "yes-no"

    monkeypatch.setitem(
        sys.modules,
        "System.Windows.Forms",
        type(
            "M",
            (),
            {"MessageBox": _MessageBox, "MessageBoxButtons": _Buttons, "DialogResult": _Result},
        ),
    )
    # The parent packages must be importable too: ``from System.Windows.Forms
    # import MessageBox`` imports the dotted chain, not just the leaf.
    for parent in ("System", "System.Windows"):
        monkeypatch.setitem(sys.modules, parent, ModuleType(parent))
    state = {"pid": 4242, "started_at": "2026-10-06T10:00:00Z"}

    assert rpl._confirm_stop_running_daemon(state) is True
    assert "4242" in shown[0]
    assert "2026-10-06T10:00:00Z" in shown[0]


def test_a_busy_pipe_mutex_refuses_the_start_and_says_which_pid(monkeypatch):
    """A second CODESYS process must not serve the same pipe."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    told = []
    error = "Daemon is already running in another CODESYS process (pid 4242). Stop it there first."
    monkeypatch.setattr(
        rpl._anchor, "acquire_pipe_mutex", lambda pipe: (None, error)
    )
    monkeypatch.setattr(
        rpl, "_notify_user", lambda message, is_error=False: told.append(message)
    )

    rpl.run_loop()

    assert timers == []  # nothing started
    assert sys._codesys_daemon_loop.get("timer") is None
    assert told == [error]
    assert "4242" in told[0]


def test_the_pipe_mutex_is_taken_at_start_and_released_on_shutdown(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    mutex = FakeMutex()
    monkeypatch.setattr(
        rpl._anchor, "acquire_pipe_mutex", lambda pipe: (mutex, None)
    )

    rpl.run_loop()
    assert sys._codesys_daemon_loop["mutex"] is mutex

    rpl.stop_daemon()

    assert mutex.released == 1
    assert mutex.closed == 1
    assert sys._codesys_daemon_loop["mutex"] is None


def test_a_tick_from_an_older_generation_retires_its_own_timer(monkeypatch):
    """A leftover instance puts itself out instead of polling the shared pipe."""
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    served = []
    monkeypatch.setattr(
        rpl, "_serve_connection", lambda pipe, dash=None: served.append(1) or False
    )
    rpl.start_daemon()
    timer = timers[0]
    # A newer run took the anchor: this run's generation is no longer current.
    sys._codesys_daemon_loop["generation"] += 1

    rpl._on_tick(None, None)

    assert served == []
    assert timer.disposals == 1
    assert timer.running is False
    assert sys._codesys_daemon_loop["timer"] is None


def test_a_stopped_generation_is_retired_too(monkeypatch):
    timers = []
    _install(monkeypatch, timers)
    _fresh_state()
    rpl.start_daemon()
    timer = timers[0]
    sys._codesys_daemon_loop["stop"] = True

    rpl._on_tick(None, None)

    assert timer.disposals == 1
    assert sys._codesys_daemon_loop["timer"] is None

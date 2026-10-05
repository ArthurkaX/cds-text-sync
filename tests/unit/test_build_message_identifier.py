# -*- coding: utf-8 -*-
"""Build-message plumbing: number conversion, and the resolver's log noise.

The number conversion must not invoke IronPython's .NET binder (``int(...)``
on a .NET value can enter the overload binder and fail with an ambiguity),
and an unresolvable message object must not cost one log line per message.
"""

import importlib.util
import sys
from pathlib import Path


BRIDGE_DIR = (
    Path(__file__).parent.parent.parent
    / "products"
    / "codesys-host"
    / "src"
    / "ide_bridge"
)

# ide_handlers_build imports its sibling bridge modules (ide_st_objects, ...)
# at module level, so loading it from a file path needs the bridge directory
# importable.  Relying on another test module having added it made collection
# order decide whether this module could even be imported.
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))


def _load_handlers_build():
    saved = {}
    for name, module in {
        "ide_daemon_state": _state_stub(),
        "ide_daemon_helpers": _helpers_stub(),
    }.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    try:
        spec = importlib.util.spec_from_file_location(
            "ide_handlers_build_under_test", BRIDGE_DIR / "ide_handlers_build.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _state_stub():
    module = type(sys)("ide_daemon_state")
    module._log = lambda *args, **kwargs: None
    module._get_active_project = lambda: (None, None)
    module._obj_name = lambda obj: ""
    return module


def _helpers_stub():
    module = type(sys)("ide_daemon_helpers")
    module._get_sync_folder = lambda *args, **kwargs: ""
    module._build_path = lambda obj: ""
    # ide_handlers_build's module-level imports must resolve against the stub.
    module._require_online_app = lambda: (
        None,
        {"ok": False, "error": "Not connected. Call connect_to_device first."},
    )
    return module


build = _load_handlers_build()


class _AmbiguousNumber:
    def __str__(self):
        return "42"


class _NonNumericNumber:
    def __str__(self):
        return "not-a-number"


def test_message_number_parses_stringified_dotnet_value():
    assert build._message_number(_AmbiguousNumber()) == 42


def test_message_number_handles_numeric_strings():
    assert build._message_number("0007") == 7
    assert build._message_number(-3) == -3


def test_message_number_ignores_non_numeric_values():
    assert build._message_number(_NonNumericNumber()) == 0
    assert build._message_number(None) == 0


class _NoName:
    """A build-message object whose name the scripting API refuses to give."""

    def get_name(self):
        raise RuntimeError("object has no name")


class _Message:
    def __init__(self, severity="Error", text="cannot convert INT to STRING", obj=None):
        self.severity = severity
        self.text = text
        self.prefix = "C"
        self.number = 32
        self.object = obj


class _System:
    def __init__(self, messages):
        self._messages = messages

    def get_message_objects(self, _category_guid):
        return self._messages


def _logged(monkeypatch):
    lines = []
    monkeypatch.setattr(build, "_log", lines.append)
    return lines


def test_an_unresolvable_object_name_is_logged_once_for_the_whole_build(monkeypatch):
    """Library and device messages carry no project object.

    That is normal and true for every such message, so one line per message
    floods the daemon log on a large project with a fact that never varies.
    """
    lines = _logged(monkeypatch)
    messages = [_Message(obj=_NoName()) for _ in range(5)]

    rows, errors, _warnings, _complete = build._collect_build_messages(_System(messages), "g")

    assert errors == 5
    assert [row["object"] for row in rows] == [""] * 5
    summary = [line for line in lines if "no project object" in line]
    assert len(summary) == 1, lines
    assert "5 build message(s)" in summary[0]


def test_a_resolvable_message_object_logs_nothing(monkeypatch):
    lines = _logged(monkeypatch)

    class _Named:
        def get_name(self):
            return "PLC_PRG"

    rows, _errors, _warnings, _complete = build._collect_build_messages(
        _System([_Message(obj=_Named())]), "g"
    )

    assert [row["object"] for row in rows] == ["PLC_PRG"]
    assert [line for line in lines if "no project object" in line] == []

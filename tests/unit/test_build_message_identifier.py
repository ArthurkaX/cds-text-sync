# -*- coding: utf-8 -*-
"""Build-message number conversion must not invoke IronPython's .NET binder."""

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

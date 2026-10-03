# -*- coding: utf-8 -*-
"""
test_daemon_config_permissions.py — the daemon config must fail closed.

A stored-but-unreadable `cds-daemon-config` leaves the user's deny list
unknown.  Falling back to the built-in defaults would be a guess, and the
Settings window's old `deny: []` fallback was worse: it looked like "nothing
is denied" and got written back on the next Apply.
"""

from __future__ import annotations

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


_saved_modules = {}
for name in _STUB_NAMES:
    _saved_modules[name] = sys.modules.get(name)
    sys.modules[name] = _stub_module(name)

if str(_IDE_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_IDE_BRIDGE))

import ide_daemon_state as ds
import ide_handlers_crc

for name, orig in _saved_modules.items():
    if orig is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = orig


class _Props:
    """Stand-in for the CODESYS project-info property bag."""

    def __init__(self, stored=None, fail_get=False, fail_set=False):
        self.stored = stored
        self.fail_get = fail_get
        self.fail_set = fail_set

    def __contains__(self, key):
        if self.fail_get:
            raise RuntimeError("property lookup blew up")
        return self.stored is not None

    def __getitem__(self, key):
        if self.fail_get:
            raise RuntimeError("property read blew up")
        if self.stored is None:
            raise KeyError(key)
        return self.stored

    def get(self, key, default=""):
        if self.fail_get:
            raise RuntimeError("property read blew up")
        return self.stored if self.stored is not None else default

    def __setitem__(self, key, value):
        if self.fail_set:
            raise RuntimeError("property write blew up")
        self.stored = value


class _ProjectInfo:
    def __init__(self, props):
        self.values = props


class _Project:
    def __init__(self, props):
        self._info = _ProjectInfo(props)

    def get_project_info(self):
        return self._info


class _Projects:
    def __init__(self, props):
        self.primary = _Project(props) if props is not None else None


def _configure(stored=None, fail_get=False, fail_set=False):
    props = _Props(stored=stored, fail_get=fail_get, fail_set=fail_set)
    sys._codesys_daemon_loop = {"projects": _Projects(props)}
    return props


def setup_function(_func):
    sys._codesys_daemon_loop = {"projects": None}


# -- _read_daemon_config: which states are which ------------------------------


def test_no_project_is_the_defaults_not_an_error():
    sys._codesys_daemon_loop = {"projects": None}
    config, status = ds._read_daemon_config()
    assert status == ds._CONFIG_MISSING
    assert config["deny"] == list(ds._DEFAULT_CONFIG["deny"])


def test_valid_config_is_merged_over_the_defaults():
    _configure(stored='{"poll_ms": 500, "deny": ["delete_pou"]}')
    config, status = ds._read_daemon_config()
    assert status == ds._CONFIG_OK
    assert config["poll_ms"] == 500
    assert config["deny"] == ["delete_pou"]
    # Unspecified keys still come from the defaults.
    assert config["copy_command"] == ds._DEFAULT_CONFIG["copy_command"]


def test_corrupt_json_is_invalid_not_missing():
    _configure(stored="{not json at all")
    config, status = ds._read_daemon_config()
    assert status == ds._CONFIG_INVALID


def test_json_that_is_not_an_object_is_invalid():
    _configure(stored='["delete_pou"]')
    _config, status = ds._read_daemon_config()
    assert status == ds._CONFIG_INVALID


def test_unreadable_property_is_invalid():
    _configure(fail_get=True)
    _config, status = ds._read_daemon_config()
    assert status == ds._CONFIG_INVALID


def test_defaults_deny_list_is_not_shared_across_reads():
    """The Settings window mutates the list; the default must not follow."""
    _configure()
    config, _status = ds._read_daemon_config()
    config["deny"].append("something_new")
    again, _status = ds._read_daemon_config()
    assert "something_new" not in again["deny"]
    assert "something_new" not in ds._DEFAULT_CONFIG["deny"]


# -- _check_permission: fail closed ------------------------------------------


def test_corrupt_config_denies_an_otherwise_allowed_command():
    _configure(stored="{not json at all")
    allowed, reason = ds._check_permission("project_tree")
    assert allowed is False
    assert "unreadable" in reason


def test_corrupt_config_keeps_denying_a_listed_command():
    _configure(stored="{not json at all")
    allowed, _reason = ds._check_permission("delete_pou")
    assert allowed is False


def test_healthy_config_still_allows_and_denies_normally():
    _configure(stored='{"deny": ["delete_pou"]}')
    assert ds._check_permission("project_tree")[0] is True
    assert ds._check_permission("delete_pou")[0] is False


def test_absent_config_keeps_the_builtin_denies():
    sys._codesys_daemon_loop = {"projects": None}
    assert ds._check_permission("reset_plc")[0] is False
    assert ds._check_permission("project_tree")[0] is True


def test_permissions_command_reports_an_unreadable_config():
    _configure(stored="{not json at all")
    payload = ide_handlers_crc._cmd_permissions()
    assert payload["ok"] is True
    assert "config_error" in payload["data"]


def test_permissions_command_has_no_error_key_when_healthy():
    _configure(stored='{"deny": []}')
    payload = ide_handlers_crc._cmd_permissions()
    assert "config_error" not in payload["data"]


# -- _save_daemon_config: failures are reported ------------------------------


def test_save_reports_success_and_persists_the_json():
    props = _configure()
    assert ds._save_daemon_config({"poll_ms": 300, "deny": []}) is True
    assert '"poll_ms": 300' in props.stored


def test_save_returns_false_when_the_write_raises():
    _configure(fail_set=True)
    assert ds._save_daemon_config({"poll_ms": 300, "deny": []}) is False


def test_save_returns_false_without_a_project():
    sys._codesys_daemon_loop = {"projects": None}
    assert ds._save_daemon_config({"poll_ms": 300, "deny": []}) is False

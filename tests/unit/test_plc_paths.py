# -*- coding: utf-8 -*-
"""PLC paths are device paths, not host paths.

``cts raw plc_files --path /`` failed live with "Get directory entries
failed" and a diagnostic ``paths_tried`` of ``["C:/Program Files/Git/"]``:
Git Bash's MSYS layer rewrites an argument that starts with ``/`` into a
Windows path *before* ``cts`` runs, so the CLI never saw the ``/`` the user
typed.  Agents work in Git Bash, so this is the common case.

Two rules follow, and they are pinned here:

* the PLC root is spelled ``.`` (or omitted) -- an empty string, not ``/``,
  because ``/`` is what MSYS eats;
* a PLC path that looks like a rewritten host path (an absolute Windows path
  with a drive letter, or a UNC share) is refused with a hint, not sent to the
  device.
"""

import os
import sys
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

import ide_handlers_plc as plc_handlers  # noqa: E402
import ide_path_guards as guards  # noqa: E402

_STATE_KEY = "_codesys_daemon_loop"
MSYS_ROOT = "C:/Program Files/Git/"


@pytest.fixture(autouse=True)
def _clean_state():
    saved = getattr(sys, _STATE_KEY, None)
    if hasattr(sys, _STATE_KEY):
        delattr(sys, _STATE_KEY)
    yield
    if saved is None:
        if hasattr(sys, _STATE_KEY):
            delattr(sys, _STATE_KEY)
    else:
        setattr(sys, _STATE_KEY, saved)


# ── the helper ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    ["C:/Program Files/Git/", "C:\\Program Files\\Git", r"\\server\share", "//server/share"],
)
def test_a_rewritten_host_path_is_recognised(value):
    assert guards.plc_path_error("path", value) is not None


@pytest.mark.parametrize("value", ["", ".", "/", "/usr/", "PlcLogic/x.bin", "codesyscontrol.log"])
def test_a_real_plc_path_is_left_alone(value):
    assert guards.plc_path_error("path", value) is None


def test_the_refusal_explains_the_root_and_the_escape():
    error = guards.plc_path_error("path", MSYS_ROOT)
    assert error["ok"] is False
    assert MSYS_ROOT in error["error"]
    assert "Git Bash" in error["error"]
    assert "pass '.'" in error["error"]
    assert "MSYS_NO_PATHCONV=1" in error["error"]


@pytest.mark.parametrize("value", [".", ""])
def test_the_root_tokens_become_the_device_root(value):
    assert guards.plc_root_path(value) == ""


def test_a_named_plc_path_is_not_touched():
    assert guards.plc_root_path("/usr/") == "/usr/"
    assert guards.plc_root_path("PlcLogic/x.bin") == "PlcLogic/x.bin"


# ── plc_files: the root is asked for without a leading slash ────────────────


class _Device(object):
    connected = True
    shared_connected = True

    def __init__(self, answer=None, only=("", "/")):
        self.calls = []
        self._answer = [] if answer is None else answer
        self._only = only

    def get_file_list_of_directory(self, path):
        self.calls.append(path)
        return self._answer if path in self._only else None


def _install_device(device):
    online_app = SimpleNamespace(get_online_device=lambda: device)
    setattr(sys, _STATE_KEY, {"online_app": online_app})


def test_plc_files_lists_the_root_from_an_empty_path():
    device = _Device()
    _install_device(device)

    result = plc_handlers._cmd_plc_files({"path": "."})

    assert result["ok"] is True
    # The first, and the successful, try is the empty string -- never a
    # Windows path MSYS could have produced.
    assert device.calls[0] == ""
    assert result["data"]["path"] == ""


def test_plc_files_without_a_path_also_asks_for_the_root():
    device = _Device()
    _install_device(device)

    plc_handlers._cmd_plc_files({})

    assert device.calls[0] == ""


def test_plc_files_refuses_an_msys_rewritten_path_before_connecting():
    device = _Device()
    _install_device(device)

    result = plc_handlers._cmd_plc_files({"path": MSYS_ROOT})

    assert result["ok"] is False
    assert "MSYS_NO_PATHCONV=1" in result["error"]
    assert device.calls == []


def test_plc_files_still_accepts_a_posix_path():
    """With MSYS_NO_PATHCONV=1 a leading '/' reaches cts as typed."""
    device = _Device(only=("/usr/",))
    _install_device(device)

    result = plc_handlers._cmd_plc_files({"path": "/usr/"})

    assert result["ok"] is True
    assert device.calls == ["/usr/"]


# ── the other PLC-path parameters ───────────────────────────────────────────


@pytest.mark.parametrize(
    "handler,params,name",
    [
        (plc_handlers._cmd_plc_log, {"file": MSYS_ROOT + "log"}, "file"),
        (plc_handlers._cmd_plc_download, {"src": MSYS_ROOT + "a.bin"}, "src"),
        (plc_handlers._cmd_plc_upload, {"dest": MSYS_ROOT + "a.bin"}, "dest"),
    ],
    ids=["plc_log", "plc_download", "plc_upload"],
)
def test_every_plc_path_parameter_is_guarded(handler, params, name):
    result = handler(params)

    assert result["ok"] is False
    assert MSYS_ROOT in result["error"]
    assert "MSYS_NO_PATHCONV=1" in result["error"]


@pytest.mark.parametrize(
    "handler,params",
    [
        (plc_handlers._cmd_plc_log, {"file": "codesyscontrol.log"}),
        (plc_handlers._cmd_plc_download, {"src": "PlcLogic/Application.crc"}),
        (plc_handlers._cmd_plc_upload, {"dest": "PlcLogic/out.bin"}),
    ],
    ids=["plc_log", "plc_download", "plc_upload"],
)
def test_a_real_plc_path_still_reaches_the_connection_check(handler, params):
    """No MSYS hint means the guard let it through; the handler then reports
    the missing session, which is the next thing it does."""
    result = handler(params)
    assert result["ok"] is False
    assert "MSYS" not in result["error"]


# ── the two kinds of path keep their own messages ───────────────────────────


def test_a_relative_host_path_still_gets_the_absolute_message():
    """plc-log --output is a host path; it must not be called a PLC path."""
    result = plc_handlers._cmd_plc_log({"output": "rel"})
    assert result["error"] == "path must be absolute: output rel"

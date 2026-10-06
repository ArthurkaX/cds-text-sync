# -*- coding: utf-8 -*-
"""Reading a PLC file that is not there -- and reading one that is.

Live, ``cts raw plc_download --src PlcLogic/codesyscontrol.log`` answered
"PLC download error: Value cannot be null. Parameter name: path." and left an
empty local file.  The file was simply not on that device (the runtime log
lives outside the file system the online device exposes), and the device's
message sent the reader looking for a bug in the path handling instead.

These tests pin the answer that replaces it: the file is looked up in its
directory first, the files that *are* there are named, and an empty local file
a failed download left behind is cleaned up.  The device is faked; the wire
behaviour needs a live PLC.
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

_STATE_KEY = "_codesys_daemon_loop"


class _DotNetDate(object):
    def __init__(self, rendered="2026-09-23T07:04:22Z"):
        self._rendered = rendered

    def ToUniversalTime(self):
        return self

    def ToString(self, fmt):
        return self._rendered


class _Entry(object):
    def __init__(self, name, size=10, is_dir=False, created=None):
        self.Name = name
        self.Length = size
        self.IsDirectory = is_dir
        if created is not None:
            self.CreationTime = created


class _Device(object):
    """A device whose file system holds exactly the directories it is given."""

    connected = True
    shared_connected = True

    def __init__(self, tree=None, upload_error=None, list_error=None):
        self.tree = tree or {}
        self.upload_error = upload_error
        self.list_error = list_error
        self.listings = []
        self.uploads = []

    def get_file_list_of_directory(self, path):
        self.listings.append(path)
        if self.list_error is not None:
            raise RuntimeError(self.list_error)
        return self.tree.get(path)

    def upload_file(self, plc_path, local_path, overwrite):
        self.uploads.append((plc_path, local_path, overwrite))
        if self.upload_error is not None:
            raise RuntimeError(self.upload_error)
        with open(local_path, "wb") as handle:
            handle.write(b"payload")


@pytest.fixture(autouse=True)
def _clean_state():
    saved = getattr(sys, _STATE_KEY, None)
    had = hasattr(sys, _STATE_KEY)
    if had:
        delattr(sys, _STATE_KEY)
    yield
    if had:
        setattr(sys, _STATE_KEY, saved)
    elif hasattr(sys, _STATE_KEY):
        delattr(sys, _STATE_KEY)


@pytest.fixture
def logged(monkeypatch):
    """Collect the daemon-log lines the handlers write."""
    lines = []
    monkeypatch.setattr(plc_handlers, "_log", lines.append)
    return lines


def _install(device):
    online_app = SimpleNamespace(get_online_device=lambda: device)
    setattr(sys, _STATE_KEY, {"online_app": online_app})


_APP_DIR = "PlcLogic/Application"


# ── plc_download ────────────────────────────────────────────────────────────


def test_a_missing_file_is_named_before_the_read_is_attempted(tmp_path, logged):
    device = _Device(tree={_APP_DIR: [_Entry("Application.crc"), _Entry("Application.app")]})
    _install(device)

    result = plc_handlers._cmd_plc_download({"src": _APP_DIR + "/codesyscontrol.log"})

    assert result["ok"] is False
    assert "codesyscontrol.log not found on the PLC file system" in result["error"]
    assert "Application.crc, Application.app" in result["error"]
    assert "CmpLog" in result["error"]
    assert device.uploads == []
    assert any("codesyscontrol.log not found" in line for line in logged)


def test_a_root_file_is_looked_up_in_the_root():
    device = _Device(tree={"": [_Entry("codesyscontrol.log")]})
    _install(device)

    result = plc_handlers._cmd_plc_download(
        {"src": "codesyscontrol.log", "dest": os.path.join(os.getcwd(), "x.log")}
    )

    assert result["ok"] is True
    assert device.listings == [""]
    assert device.uploads[0][0] == "codesyscontrol.log"


def test_a_present_file_downloads_to_a_non_empty_default_destination():
    device = _Device(tree={_APP_DIR: [_Entry("Application.crc")]})
    _install(device)

    result = plc_handlers._cmd_plc_download({"src": _APP_DIR + "/Application.crc"})

    assert result["ok"] is True
    assert result["data"]["destination"]
    assert os.path.isfile(result["data"]["destination"])
    assert result["data"]["size"] == len(b"payload")
    os.remove(result["data"]["destination"])


def test_a_device_failure_names_the_path_and_the_raw_error(tmp_path, logged):
    dest = tmp_path / "out.log"
    dest.write_bytes(b"")  # a stale, empty file the download would overwrite
    device = _Device(
        tree={"": [_Entry("codesyscontrol.log")]}, upload_error="device refused"
    )
    _install(device)

    result = plc_handlers._cmd_plc_download(
        {"src": "codesyscontrol.log", "dest": str(dest)}
    )

    assert result["ok"] is False
    assert result["error"] == (
        "Reading codesyscontrol.log from the PLC failed: device refused"
    )
    # The empty destination is cleaned up rather than left looking like a
    # successful, empty download.
    assert not dest.exists()
    assert any("reading codesyscontrol.log failed" in line for line in logged)


def test_a_failed_listing_does_not_become_a_false_not_found(tmp_path, logged):
    """If the directory cannot be listed, let the read report its own error."""
    dest = tmp_path / "out.log"
    device = _Device(list_error="not connected", upload_error="still refused")
    _install(device)

    result = plc_handlers._cmd_plc_download(
        {"src": "codesyscontrol.log", "dest": str(dest)}
    )

    assert result["ok"] is False
    assert "could not list" not in result["error"]
    assert result["error"] == "Reading codesyscontrol.log from the PLC failed: still refused"
    assert any("could not list the PLC root" in line for line in logged)


# ── plc_log ─────────────────────────────────────────────────────────────────


def test_plc_log_of_a_missing_file_says_where_the_log_may_be(logged):
    device = _Device(tree={"": [_Entry("PlcLogic", size=0, is_dir=True)]})
    _install(device)

    result = plc_handlers._cmd_plc_log({"file": "codesyscontrol.log", "tail": "5"})

    assert result["ok"] is False
    assert result["error"].startswith("codesyscontrol.log not found")
    assert "/var/volatile/log/codesyscontrol.log" in result["error"]


def test_the_log_listing_never_offers_a_directory_as_a_log():
    device = _Device(
        tree={
            "": [
                _Entry("PlcLogic", size=0, is_dir=True),
                _Entry("codesyscontrol.log"),
                _Entry("notes.txt"),
            ]
        }
    )
    _install(device)

    result = plc_handlers._cmd_plc_log({})

    assert result["ok"] is True
    names = [f["name"] for f in result["data"]["log_files"]]
    assert names == ["codesyscontrol.log"]
    assert "PlcLogic" not in names


def test_an_empty_log_listing_says_so_plainly():
    device = _Device(tree={"": [_Entry("PlcLogic", size=0, is_dir=True)]})
    _install(device)

    result = plc_handlers._cmd_plc_log({})

    assert result["ok"] is True
    assert result["data"]["count"] == 0
    assert "no log files" in result["data"]["note"]


def test_a_log_listing_carries_iso_creation_times():
    device = _Device(tree={"": [_Entry("codesyscontrol.log", created=_DotNetDate())]})
    _install(device)

    result = plc_handlers._cmd_plc_log({})

    assert result["data"]["log_files"][0]["creation_time"] == "2026-09-23T07:04:22Z"


def test_a_failed_log_listing_is_logged(logged):
    device = _Device(list_error="Get directory entries failed")
    _install(device)

    result = plc_handlers._cmd_plc_log({})

    assert result["ok"] is False
    assert "Get directory entries failed" in result["error"]
    assert any("listing the log directory failed" in line for line in logged)


# ── plc_files ───────────────────────────────────────────────────────────────


def test_plc_files_lists_entries_with_iso_times_and_a_directory_flag():
    device = _Device(
        tree={
            "": [
                _Entry("PlcLogic", size=0, is_dir=True),
                _Entry("codesyscontrol.log", created=_DotNetDate()),
            ]
        }
    )
    _install(device)

    result = plc_handlers._cmd_plc_files({})

    assert result["ok"] is True
    by_name = {f["name"]: f for f in result["data"]["files"]}
    assert by_name["PlcLogic"]["is_directory"] is True
    assert by_name["codesyscontrol.log"]["creation_time"] == "2026-09-23T07:04:22Z"


def test_plc_files_logs_a_failed_listing(logged):
    device = _Device(list_error="Get directory entries failed")
    _install(device)

    result = plc_handlers._cmd_plc_files({})

    assert result["ok"] is False
    assert result["error"] == "Get directory entries failed"
    assert any("plc_files:" in line for line in logged)

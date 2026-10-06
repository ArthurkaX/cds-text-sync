# -*- coding: utf-8 -*-
"""The shared PLC file listing: ISO-UTC timestamps, directories, lookups.

Live, ``cts plc-log`` listed a *directory* (``PlcLogic``, size 0) among the
log files, the timestamps came back as the device's .NET default text
("9/23/2026 7:04:22 AM"), and a file that was not on the device surfaced as
"Upload file error: Value cannot be null. Parameter name: path." -- which read
as a bug in the path handling rather than "that file is not there".

``ide_plc_files`` is where those three answers now live, so they are pinned
here once instead of in each handler.
"""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import ide_plc_files as plc_files  # noqa: E402


class _DotNetDate(object):
    """Enough of ``System.DateTime`` for the formatter."""

    def __init__(self, rendered="2026-09-23T07:04:22Z"):
        self._rendered = rendered

    def ToUniversalTime(self):
        return self

    def ToString(self, fmt):
        return self._rendered


class _Entry(object):
    def __init__(self, name, size=None, is_dir=None, created=None, modified=None):
        self.Name = name
        if size is not None:
            self.Length = size
        if is_dir is not None:
            self.IsDirectory = is_dir
        if created is not None:
            self.CreationTime = created
        if modified is not None:
            self.LastWriteTime = modified


class _Device(object):
    def __init__(self, entries=None, error=None):
        self.entries = [] if entries is None else entries
        self.error = error
        self.calls = []

    def get_file_list_of_directory(self, path):
        self.calls.append(path)
        if self.error is not None:
            raise RuntimeError(self.error)
        return self.entries


# ── timestamps ──────────────────────────────────────────────────────────────


def test_a_device_datetime_becomes_iso_utc():
    assert plc_files.iso_utc(_DotNetDate()) == "2026-09-23T07:04:22Z"


def test_the_format_ends_in_a_literal_z():
    assert plc_files.ISO_UTC_FORMAT.endswith("Z")


def test_a_missing_timestamp_is_empty():
    assert plc_files.iso_utc(None) == ""


def test_a_plain_string_is_left_as_the_device_wrote_it():
    assert plc_files.iso_utc("9/23/2026 7:04:22 AM") == "9/23/2026 7:04:22 AM"


def test_a_python_datetime_is_formatted():
    assert plc_files.iso_utc(datetime(2026, 9, 23, 7, 4, 22)) == "2026-09-23T07:04:22Z"


# ── one entry ───────────────────────────────────────────────────────────────


def test_a_file_entry_is_described_with_iso_time():
    entry = _Entry("codesyscontrol.log", size=2048, is_dir=False, created=_DotNetDate())

    info = plc_files.describe_entry(entry)

    assert info["name"] == "codesyscontrol.log"
    assert info["size"] == 2048
    assert info["is_directory"] is False
    assert info["creation_time"] == "2026-09-23T07:04:22Z"


def test_a_directory_entry_is_flagged():
    info = plc_files.describe_entry(_Entry("PlcLogic", size=0, is_dir=True))

    assert info["is_directory"] is True


def test_a_string_directory_flag_is_not_truthy_by_accident():
    """bool("False") is True; a device that answers with text must not lie."""
    info = plc_files.describe_entry(_Entry("x", is_dir="False"))

    assert info["is_directory"] is False


def test_a_snake_case_entry_is_understood():
    entry = SimpleNamespace(name="a.log", size=3, is_directory=True)

    info = plc_files.describe_entry(entry)

    assert info == {"name": "a.log", "size": 3, "is_directory": True}


def test_an_entry_without_a_name_keeps_something_to_identify_it():
    info = plc_files.describe_entry(SimpleNamespace())

    assert info["name"]


# ── a whole directory ───────────────────────────────────────────────────────


def test_the_root_token_asks_the_device_for_the_empty_path():
    device = _Device()

    entries, error = plc_files.list_directory(device, ".")

    assert error is None
    assert entries == []
    assert device.calls == [""]


def test_a_failed_listing_is_not_an_empty_directory():
    device = _Device(error="Get directory entries failed")

    entries, error = plc_files.list_directory(device, "PlcLogic")

    assert entries is None
    assert "directory entries" in error


def test_a_device_that_answers_none_is_an_empty_directory():
    class _NoneDevice(_Device):
        def get_file_list_of_directory(self, path):
            return None

    entries, error = plc_files.list_directory(_NoneDevice(), "")

    assert entries == []
    assert error is None


# ── looking a file up ───────────────────────────────────────────────────────


def test_lookup_finds_the_file_in_its_parent_directory():
    device = _Device([_Entry("Application.crc"), _Entry("Application.app")])

    present, entries, parent, error = plc_files.lookup(
        device, "PlcLogic/Application/Application.crc"
    )

    assert present is True
    assert parent == "PlcLogic/Application"
    assert device.calls == ["PlcLogic/Application"]
    assert [e["name"] for e in entries] == ["Application.crc", "Application.app"]


def test_lookup_of_a_root_file_asks_the_root():
    device = _Device([_Entry("codesyscontrol.log")])

    present, _entries, parent, _error = plc_files.lookup(device, "codesyscontrol.log")

    assert present is True
    assert parent == ""
    assert device.calls == [""]


def test_lookup_reports_a_missing_file():
    device = _Device([_Entry("Application.crc")])

    present, _entries, _parent, error = plc_files.lookup(
        device, "PlcLogic/Application/missing.log"
    )

    assert present is False
    assert error is None


def test_lookup_says_nothing_when_the_listing_itself_failed():
    """A failed listing must not be reported as "the file is not there"."""
    device = _Device(error="not connected")

    present, entries, _parent, error = plc_files.lookup(device, "a/b.log")

    assert present is None
    assert entries is None
    assert error == "not connected"


def test_lookup_is_case_insensitive_as_a_fallback():
    device = _Device([_Entry("PlcLogic")])

    present, _entries, _parent, _error = plc_files.lookup(device, "plclogic")

    assert present is True


# ── the "not found" message ─────────────────────────────────────────────────


def test_the_not_found_message_names_the_files_that_are_there():
    entries = plc_files.list_directory(
        _Device([_Entry("PlcLogic", is_dir=True), _Entry("a.log"), _Entry("b.txt")]), ""
    )[0]

    error = plc_files.missing_file_error("codesyscontrol.log", entries, "")

    assert error["ok"] is False
    assert "codesyscontrol.log not found on the PLC file system" in error["error"]
    assert "a.log, b.txt" in error["error"]
    # The directory is not offered as if it were a file.
    assert "PlcLogic" not in error["error"]


def test_the_not_found_message_explains_the_log_may_be_off_the_device_fs():
    error = plc_files.missing_file_error("codesyscontrol.log", [], "")

    assert "/var/volatile/log/codesyscontrol.log" in error["error"]
    assert "CmpLog" in error["error"]


def test_the_not_found_message_says_so_when_the_directory_is_empty():
    error = plc_files.missing_file_error("x.log", [], "PlcLogic")

    assert "files in PlcLogic: no files" in error["error"]


def test_the_parent_of_a_named_file_is_its_directory():
    assert plc_files.plc_parent("PlcLogic/Application/Application.crc") == (
        "PlcLogic/Application"
    )
    assert plc_files.plc_parent("codesyscontrol.log") == ""
    assert plc_files.plc_name("a\\b\\c.log") == "c.log"

# -*- coding: utf-8 -*-
"""The PLC log download is handed a real, non-empty local destination.

Live, ``cts plc-log --tail ...`` (and the ``--cts`` scratch flow) came back
"Upload file error: Value cannot be null. Parameter name: path."  The only
path on this side is the local destination the daemon downloads the log
into, and it was named with ``tempfile.mktemp`` -- which only *names* a file:
it need not exist, and there is no check that it is usable before it goes to
the device API.  It is built with ``mkstemp`` now, so the path exists in a
writable directory by construction.

These tests fake the online device: without a live PLC the wire behaviour
cannot be reproduced, but the invariant the fix rests on can.
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


class _Device(object):
    """The parts of the CODESYS online device the log reader uses."""

    connected = True
    shared_connected = True

    def __init__(self, payload=b"first\nsecond\nthird\n"):
        self.payload = payload
        self.uploads = []

    def upload_file(self, plc_path, local_path, overwrite):
        self.uploads.append((plc_path, local_path, overwrite))
        # The device writes the log to the local path it was handed.
        with open(local_path, "wb") as handle:
            handle.write(self.payload)


def _install(device):
    online_app = SimpleNamespace(get_online_device=lambda: device)
    setattr(sys, _STATE_KEY, {"online_app": online_app})


def test_the_download_destination_is_a_real_path(tmp_path, monkeypatch):
    """mktemp only names a file; the destination must exist when it is used."""
    device = _Device()
    _install(device)
    checked = {}

    real_upload = device.upload_file

    def upload(plc_path, local_path, overwrite):
        checked["destination"] = local_path
        checked["exists"] = os.path.isfile(local_path)
        return real_upload(plc_path, local_path, overwrite)

    monkeypatch.setattr(device, "upload_file", upload)

    result = plc_handlers._cmd_plc_log({"file": "codesyscontrol.log", "tail": "2"})

    assert result["ok"] is True
    assert checked["destination"], "the destination path must not be empty"
    assert checked["exists"], (
        "the destination handed to the device API must be a real path"
    )


def test_a_tail_download_uses_a_non_empty_destination():
    device = _Device()
    _install(device)

    result = plc_handlers._cmd_plc_log({"file": "codesyscontrol.log", "tail": "2"})

    assert result["ok"] is True
    plc_path, local_path, overwrite = device.uploads[0]
    assert plc_path == "codesyscontrol.log"
    assert local_path
    assert overwrite is True
    assert result["data"]["tail"] == ["second", "third"]


@pytest.mark.parametrize("value", [None, ""])
def test_a_null_or_empty_log_name_falls_back_to_the_default(value):
    """`params.get("file", default)` returns None when the key is present and
    null; that None reached the device API as the path to read."""
    device = _Device()
    _install(device)

    result = plc_handlers._cmd_plc_log({"file": value, "tail": "2"})

    assert result["ok"] is True
    plc_path = device.uploads[0][0]
    assert plc_path == "codesyscontrol.log"


def test_a_download_without_tail_or_output_still_has_a_destination(tmp_path):
    """The --output scratch flow downloads the same way."""
    device = _Device()
    _install(device)
    out = tmp_path / "saved"
    out.mkdir()

    result = plc_handlers._cmd_plc_log(
        {"file": "codesyscontrol.log", "output": str(out)}
    )

    assert result["ok"] is True
    local_path = device.uploads[0][1]
    assert local_path
    # The log was copied next to the requested output path.
    assert os.path.isfile(out / "codesyscontrol.log")
    assert result["data"]["saved_to"] == str(out / "codesyscontrol.log")


def test_a_device_failure_names_the_error_without_a_null_path():
    class _Failing(_Device):
        def upload_file(self, plc_path, local_path, overwrite):
            raise RuntimeError("device refused")

    _install(_Failing())

    result = plc_handlers._cmd_plc_log({"file": "codesyscontrol.log", "tail": "2"})

    assert result["ok"] is False
    assert result["error"] == "Upload file error: device refused"

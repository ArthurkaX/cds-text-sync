# -*- coding: utf-8 -*-
"""The shared online-session preamble helpers.

Every online handler used to open with the same lines: read the daemon's
``online_app``, answer "Not connected." when it is absent, then resolve
``get_online_device()`` and answer "get_online_device() returned None" when
that fails. ``ide_daemon_helpers._require_online_app`` /
``_require_online_device`` hold that block once now. These tests pin both the
return values of the helpers and the exact responses the handlers still send,
because the message text is part of the wire contract.
"""

import os
import sys

import pytest


_IDE_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "products",
        "codesys-host",
        "src",
        "ide_bridge",
    )
)
if _IDE_BRIDGE not in sys.path:
    sys.path.insert(0, _IDE_BRIDGE)

import ide_daemon_helpers as helpers
import ide_handlers_crc as crc_handlers
import ide_handlers_plc as plc_handlers


NOT_CONNECTED = {"ok": False, "error": "Not connected. Call connect_to_device first."}
NO_DEVICE = {"ok": False, "error": "get_online_device() returned None"}


class _Oa(object):
    def __init__(self, device):
        self._device = device

    def get_online_device(self):
        return self._device


def _install_loop(monkeypatch, **state):
    monkeypatch.setattr(sys, "_codesys_daemon_loop", state, raising=False)


# ── _require_online_app ───────────────────────────────────────────────────


def test_require_online_app_returns_the_session(monkeypatch):
    oa = _Oa(object())
    _install_loop(monkeypatch, online_app=oa)
    assert helpers._require_online_app() == (oa, None)


def test_require_online_app_reports_a_missing_session(monkeypatch):
    _install_loop(monkeypatch)
    assert helpers._require_online_app() == (None, NOT_CONNECTED)


# ── _require_online_device ────────────────────────────────────────────────


def test_require_online_device_returns_the_device(monkeypatch):
    device = object()
    oa = _Oa(device)
    _install_loop(monkeypatch, online_app=oa)
    assert helpers._require_online_device() == (oa, device, None)


def test_require_online_device_reports_a_missing_session(monkeypatch):
    _install_loop(monkeypatch)
    assert helpers._require_online_device() == (None, None, NOT_CONNECTED)


def test_require_online_device_reports_a_missing_device(monkeypatch):
    oa = _Oa(None)
    _install_loop(monkeypatch, online_app=oa)
    assert helpers._require_online_device() == (oa, None, NO_DEVICE)


# ── handler-level byte-for-byte responses ─────────────────────────────────


@pytest.mark.parametrize(
    "handler,params",
    [
        (plc_handlers._cmd_plc_log, {}),
        (crc_handlers._cmd_app_crc, {}),
    ],
)
def test_handlers_keep_the_not_connected_response(monkeypatch, handler, params):
    _install_loop(monkeypatch)
    assert handler(params) == NOT_CONNECTED


@pytest.mark.parametrize(
    "handler,params",
    [
        (plc_handlers._cmd_plc_files, {}),
        (crc_handlers._cmd_app_crc, {}),
    ],
)
def test_handlers_keep_the_missing_device_response(monkeypatch, handler, params):
    _install_loop(monkeypatch, online_app=_Oa(None))
    assert handler(params) == NO_DEVICE


def test_online_app_only_handlers_keep_the_not_connected_response(monkeypatch):
    _install_loop(monkeypatch)
    assert plc_handlers._cmd_create_boot_app() == NOT_CONNECTED
    assert crc_handlers._cmd_app_info() == NOT_CONNECTED

# -*- coding: utf-8 -*-
"""
test_cli_handlers_daemon.py -- Tests for the top-level daemon-command dispatch.

dispatch_daemon was extracted from main(); it carries the few commands that
are more than pure routing. These tests pin: the passthrough table, the
import --dry-run and the refusal of any online override, plc-crc
build-first ordering, download --start passthrough, the write read-back,
and the "return False for anything I don't handle" contract.
"""

import argparse
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_cli import _cli_handlers_daemon as d


@pytest.fixture
def daemon_calls(monkeypatch):
    """Record cmd_daemon(method, params, ...) calls in order."""
    calls = []

    def _fake_cmd_daemon(method, params=None, timeout=15, output_fmt="json"):
        calls.append((method, params or {}))

    monkeypatch.setattr(d, "cmd_daemon", _fake_cmd_daemon)
    return calls


def _args(**kwargs):
    kwargs.setdefault("timeout", 15)
    return argparse.Namespace(**kwargs)


def test_passthrough_ping(daemon_calls):
    handled = d.dispatch_daemon(_args(command="ping"))
    assert handled is True
    assert daemon_calls == [("ping", {})]


def test_export_maps_to_sync_method(daemon_calls):
    d.dispatch_daemon(_args(command="export"))
    assert daemon_calls == [("sync_export_text", {})]


def test_import_dry_run_previews_compare(daemon_calls):
    handled = d.dispatch_daemon(
        _args(command="import", dry_run=True, force_online=False)
    )
    assert handled is True
    # Only the compare preview runs; sync_import_text must NOT.
    assert daemon_calls == [("sync_compare_text", {})]


def test_import_does_not_allow_online_override(daemon_calls):
    d.dispatch_daemon(_args(command="import", dry_run=False, force_online=True))
    assert daemon_calls == [("sync_import_text", {})]


def test_plc_crc_builds_first(daemon_calls):
    d.dispatch_daemon(_args(command="plc-crc", build=True))
    # build runs before the CRC comparison. The daemon method is plc_crc, not
    # "compare" -- that older name made the daemon log read as if `cts compare`
    # were running, which is a different command entirely.
    assert daemon_calls == [("build", {}), ("plc_crc", {})]


def test_build_uses_daemon_startup_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        d,
        "send_command_reverse",
        lambda method, params=None, timeout=15: {
            "ok": True,
            "data": {"timeout_profile": {"block_count": 42, "timeouts": {"build": 321}}},
        },
    )
    monkeypatch.setattr(
        d,
        "cmd_daemon",
        lambda method, params=None, timeout=15, output_fmt="json": calls.append(
            (method, params or {}, timeout)
        ),
    )

    d.dispatch_daemon(_args(command="build", timeout=None))

    assert calls == [("build", {}, 321)]


def test_explicit_build_timeout_is_not_recalculated(monkeypatch):
    calls = []
    monkeypatch.setattr(
        d,
        "send_command_reverse",
        lambda *args, **kwargs: pytest.fail("profile must not be queried"),
    )
    monkeypatch.setattr(
        d,
        "cmd_daemon",
        lambda method, params=None, timeout=15, output_fmt="json": calls.append(
            (method, params or {}, timeout)
        ),
    )

    d.dispatch_daemon(_args(command="build", timeout=42))

    assert calls == [("build", {}, 42)]


def test_download_start_passthrough(daemon_calls):
    d.dispatch_daemon(_args(command="download", start=True))
    assert daemon_calls == [("download", {"start": True})]


def test_connect_maps_ip_and_gateway(daemon_calls):
    d.dispatch_daemon(_args(command="connect", ip="1.2.3.4", gateway="GW"))
    assert daemon_calls == [
        ("connect_to_device", {"ipAddress": "1.2.3.4", "gatewayName": "GW"})
    ]


def test_unknown_command_returns_false(daemon_calls):
    handled = d.dispatch_daemon(_args(command="variable-map"))
    assert handled is False
    assert daemon_calls == []


def test_write_does_read_back(monkeypatch, capsys):
    sent = []

    def _fake_send(method, params=None, timeout=15):
        sent.append((method, params))
        if method == "read_variable":
            return {"ok": True, "data": {"value": "42"}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(d, "send_command_reverse", _fake_send)
    handled = d.dispatch_daemon(
        _args(command="write", name="MyVar", value="42"), output_fmt="json"
    )
    assert handled is True
    assert [m for m, _ in sent] == ["write_variable", "read_variable"]
    out = capsys.readouterr().out
    assert "read_back" in out and "42" in out


def test_write_failure_exits_nonzero(monkeypatch):
    def _fake_send(method, params=None, timeout=15):
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr(d, "send_command_reverse", _fake_send)
    with pytest.raises(SystemExit) as exc:
        d.dispatch_daemon(_args(command="write", name="X", value="1"))
    assert exc.value.code == 1

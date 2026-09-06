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


def test_set_sync_folder_maps_path_and_save(daemon_calls):
    d.dispatch_daemon(
        _args(command="set-sync-folder", path=r"C:\Sync\Demo", save=True)
    )
    assert daemon_calls == [
        ("set_sync_folder", {"path": r"C:\Sync\Demo", "save": True})
    ]


def test_set_sync_folder_omits_path_for_automatic_setup(daemon_calls):
    d.dispatch_daemon(_args(command="set-sync-folder", path="", save=False))
    assert daemon_calls == [("set_sync_folder", {})]


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
            "data": {"block_count": 42, "timeouts": {"build": 321}},
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


def test_timeout_lookup_does_not_call_status(monkeypatch):
    methods = []
    monkeypatch.setattr(
        d,
        "send_command_reverse",
        lambda method, params=None, timeout=15: methods.append(method)
        or {"ok": True, "data": {"timeouts": {"build": 321}}},
    )

    assert d._daemon_timeout("build") == 321
    assert methods == ["timeout_profile"]


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


# ===================================================================
# Phase 3 Step 3.4: Raw CLI Parsing Tests
# ===================================================================


class TestRawCliParsing:
    def test_valid_key_value_pairs(self):
        from cds_cli._cli_io import _parse_key_value_args

        args = ["--timeout", "10", "--name", "Main", "--app_dir", "Device/Plc"]
        params = _parse_key_value_args(args)
        assert params == {
            "timeout": "10",
            "name": "Main",
            "app_dir": "Device/Plc",
        }

    def test_boolean_flags(self):
        from cds_cli._cli_io import _parse_key_value_args

        args = ["--verbose", "--force", "--timeout", "5"]
        params = _parse_key_value_args(args)
        assert params == {
            "verbose": True,
            "force": True,
            "timeout": "5",
        }

    def test_negative_numeric_values(self):
        from cds_cli._cli_io import _parse_key_value_args

        args = ["--offset", "-5", "--scale", "-1.25", "--flag"]
        params = _parse_key_value_args(args)
        assert params == {
            "offset": "-5",
            "scale": "-1.25",
            "flag": True,
        }

    def test_unexpected_positional_arguments_exit_nonzero(self, capsys):
        from cds_cli._cli_io import _parse_key_value_args

        with pytest.raises(SystemExit) as exc:
            _parse_key_value_args(["extra_arg"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Unexpected positional argument: extra_arg" in err

    def test_multiple_unexpected_positional_arguments(self, capsys):
        from cds_cli._cli_io import _parse_key_value_args

        with pytest.raises(SystemExit) as exc:
            _parse_key_value_args(["arg1", "arg2"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Unexpected positional argument: arg1" in err

    def test_positional_argument_following_valid_pair(self, capsys):
        from cds_cli._cli_io import _parse_key_value_args

        with pytest.raises(SystemExit) as exc:
            _parse_key_value_args(["--key", "value", "stray_arg"])
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Unexpected positional argument: stray_arg" in err

    def test_identical_failure_behavior_through_raw_and_rp(self, monkeypatch, capsys):
        from cds_cli._cli_io import cmd_rp_command
        import cds_cli.main as cli_main

        # Ensure send_command_reverse is never reached
        def _must_not_call(*args, **kwargs):
            pytest.fail("send_command_reverse should not be called when arguments are invalid")

        monkeypatch.setattr("cds_cli._cli_io.send_command_reverse", _must_not_call)
        monkeypatch.setattr("cds_cli.main.send_command_reverse", _must_not_call)

        # 1. Direct cmd_rp_command invocation with invalid positional
        with pytest.raises(SystemExit) as exc1:
            cmd_rp_command(["ping", "unexpected_positional"])
        assert exc1.value.code == 1
        err1 = capsys.readouterr().err
        assert "Unexpected positional argument: unexpected_positional" in err1

        # 2. Dispatch through main() with "raw"
        monkeypatch.setattr(
            sys, "argv", ["cts", "raw", "ping", "unexpected_positional"]
        )
        with pytest.raises(SystemExit) as exc2:
            cli_main.main()
        assert exc2.value.code == 1
        err2 = capsys.readouterr().err
        assert "Unexpected positional argument: unexpected_positional" in err2

        # 3. Dispatch through main() with deprecated "rp" alias
        monkeypatch.setattr(
            sys, "argv", ["cts", "rp", "ping", "unexpected_positional"]
        )
        with pytest.raises(SystemExit) as exc3:
            cli_main.main()
        assert exc3.value.code == 1
        err3 = capsys.readouterr().err
        assert "Unexpected positional argument: unexpected_positional" in err3

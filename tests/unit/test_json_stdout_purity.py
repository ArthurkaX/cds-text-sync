# -*- coding: utf-8 -*-
"""
test_json_stdout_purity.py — stdout carries the payload and nothing else.

Live, a "[INFO] Timeout: 180s for 342 ST block(s)" line arrived on stdout ahead
of the JSON payload and broke the caller's parser.  Progress chatter belongs on
stderr: stdout is the machine-readable channel, and an agent that pipes it
straight into a JSON reader must not have to skip lines first.

These tests pin the invariant for the daemon-command family, including the one
command family that announces a resolved timeout before it runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cds_cli import _cli_handlers_daemon as d  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_timeout_cache():
    """The timeout profile is cached per process; each test needs its own."""
    saved = dict(d._TIMEOUT_PROFILE_CACHE)
    d._TIMEOUT_PROFILE_CACHE["fetched"] = False
    d._TIMEOUT_PROFILE_CACHE["value"] = None
    yield
    d._TIMEOUT_PROFILE_CACHE.update(saved)


def _args(**kwargs):
    import argparse

    kwargs.setdefault("timeout", None)
    return argparse.Namespace(**kwargs)


def _profile_response(method, params=None, timeout=15):
    if method == "timeout_profile":
        return {"ok": True, "data": {"block_count": 342, "timeouts": {"build": 321}}}
    return {"ok": True, "data": {"messages": [], "count": 0}}


def test_the_timeout_announcement_goes_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(d, "send_command_reverse", _profile_response)

    value = d._daemon_timeout("build")

    captured = capsys.readouterr()
    assert value == 321.0
    assert "Timeout: 321s" in captured.err
    assert captured.out == ""


def test_a_json_daemon_command_writes_only_json_to_stdout(monkeypatch, capsys):
    """The exact live complaint: an info line ahead of the JSON payload."""
    monkeypatch.setattr(d, "send_command_reverse", _profile_response)
    monkeypatch.setattr(
        d, "cmd_daemon", lambda *a, **k: print(json.dumps({"ok": True}))
    )

    d.dispatch_daemon(_args(command="build"), output_fmt="json")

    out = capsys.readouterr().out
    assert json.loads(out) == {"ok": True}
    assert "[INFO]" not in out
    assert out.startswith("{")
    assert out.count("\n") == 1


def test_no_daemon_command_writes_anything_but_its_payload(monkeypatch, capsys):
    """Every passthrough command, not just build: stdout starts with the JSON."""
    monkeypatch.setattr(d, "send_command_reverse", _profile_response)
    monkeypatch.setattr(
        d, "cmd_daemon", lambda *a, **k: print(json.dumps({"ok": True}))
    )

    for command in ("ping", "status", "compare", "import", "plc-crc"):
        captured = capsys.readouterr()
        assert captured.out == ""
        d.dispatch_daemon(_args(command=command), output_fmt="json")
        out = capsys.readouterr().out
        assert json.loads(out) == {"ok": True}, command


def test_an_explicit_timeout_announces_nothing(monkeypatch, capsys):
    """Nothing to resolve means nothing to say -- and nothing on stdout."""
    monkeypatch.setattr(d, "send_command_reverse", _profile_response)

    assert d._daemon_timeout("build", requested_timeout=60) == 60

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[INFO]" not in captured.err


def test_the_import_refusal_announces_no_timeout(monkeypatch, capsys):
    """An online import is refused at once; announcing a timeout first reads
    as if the command had started."""
    monkeypatch.setattr(d, "send_command_reverse", _profile_response)

    d._daemon_timeout("sync_import_text")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[INFO]" not in captured.err


def test_stderr_helpers_never_touch_stdout(monkeypatch, capsys):
    from cds_cli import _cli_io

    _cli_io._print_info("info")
    _cli_io._print_ok("ok")
    _cli_io._print_warn("warn")
    _cli_io._print_error("error")

    captured = capsys.readouterr()
    assert captured.out == ""
    for level in ("[INFO]", "[OK]", "[WARN]", "[ERROR]"):
        assert level in captured.err

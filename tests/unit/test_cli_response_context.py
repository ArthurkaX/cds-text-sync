# -*- coding: utf-8 -*-
"""
test_cli_response_context.py — the CLI half of the response ``context``.

The daemon attaches ``context`` to its envelope; the CLI hoists it into the
printed JSON (like ``instance``) and, in text mode, ends with one ``[ctx]``
line. JSON mode must not write anything extra to stderr. A daemon that does
not answer gets one honest extra line, never a fabricated state.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cds_cli import _cli_io  # noqa: E402
from cds_cli._cli_io import _context_line, _format_output  # noqa: E402


ONLINE = {
    "project": "cts-reference-project",
    "ide": "ide-3444",
    "plc": {"online": True, "state": "run", "application": "Application"},
    "edits_allowed": False,
    "hint": "The IDE is online with the PLC; project edits are refused.",
    "hint_short": "cts disconnect",
    "age_s": 3,
}

OFFLINE = {
    "project": "cts-reference-project",
    "ide": "ide-3444",
    "plc": {"online": False, "state": "stop", "application": "Application"},
    "edits_allowed": True,
    "age_s": 12,
}

UNKNOWN = {
    "project": None,
    "ide": "ide-3444",
    "plc": {"online": None, "state": "", "application": ""},
    "edits_allowed": None,
    "hint": "The daemon holds no cached PLC session; the IDE may still be online.",
    "hint_short": "cts disconnect",
    "age_s": 900,
}


@pytest.fixture
def with_context(monkeypatch):
    def install(context):
        monkeypatch.setattr(_cli_io, "get_last_context", lambda: context)
        monkeypatch.setattr(_cli_io, "get_last_instance", lambda: None)

    return install


# ── text mode: the one ``[ctx]`` line ──────────────────────────────────────


def test_online_renders_blocked_with_the_action(with_context):
    with_context(ONLINE)
    rendered = _format_output({"action": "tree"}, "text")
    assert rendered.endswith(
        "[ctx] project=cts-reference-project ide=ide-3444 "
        "plc=online/run edits=blocked (cts disconnect)"
    )


def test_offline_renders_allowed_and_no_parens(with_context):
    with_context(OFFLINE)
    line = _format_output({"x": 1}, "text").splitlines()[-1]
    assert line == (
        "[ctx] project=cts-reference-project ide=ide-3444 "
        "plc=offline/stop edits=allowed"
    )


def test_unknown_plc_is_spelled_unknown(with_context):
    with_context(UNKNOWN)
    line = _format_output({"x": 1}, "text").splitlines()[-1]
    assert "plc=unknown" in line
    # Unknown edits must not read as permission: live, "edits=allowed" was
    # printed while the next edit was refused.
    assert "edits=unknown" in line


def test_a_missing_context_keeps_the_legacy_instance_line(monkeypatch, with_context):
    with_context(None)
    monkeypatch.setattr(
        _cli_io,
        "get_last_instance",
        lambda: {"id": "ide-3684", "project": {"name": "VKO"}},
    )
    assert _format_output({"x": 1}, "text").endswith("ide-3684 · VKO")


def test_a_partial_context_does_not_crash(with_context):
    with_context({"project": "P", "ide": "ide-1"})
    line = _context_line({"project": "P", "ide": "ide-1"})
    assert line == "[ctx] project=P ide=ide-1 plc=unknown edits=unknown"


def test_context_line_is_empty_without_a_context():
    assert _context_line(None) == ""
    assert _context_line("nonsense") == ""


# ── JSON mode: top level, additive, no stderr noise ────────────────────────


def test_json_hoists_context_at_the_top_level(with_context):
    with_context(ONLINE)
    parsed = json.loads(_format_output({"status": "pong"}, "json"))
    assert parsed["status"] == "pong"
    assert parsed["context"]["project"] == "cts-reference-project"


def test_json_mode_writes_nothing_to_stderr(with_context, capsys):
    with_context(ONLINE)
    _format_output({"status": "pong"}, "json")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_json_does_not_overwrite_a_context_already_in_the_payload(with_context):
    with_context(ONLINE)
    payload = {"status": "pong", "context": {"project": "inner"}}
    parsed = json.loads(_format_output(payload, "json"))
    assert parsed["context"] == {"project": "inner"}


# ── item 5: the daemon-unreachable line ────────────────────────────────────


def test_unreachable_line_is_printed_on_a_pipe_failure(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("Timeout waiting for IDE response to 'ping'")

    monkeypatch.setattr(_cli_io, "send_command_reverse", boom)
    with pytest.raises(SystemExit) as exc:
        _cli_io.cmd_daemon("ping", {}, output_fmt="json")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Timeout waiting for IDE response" in err
    assert "The IDE/daemon is not answering" in err


def test_unreachable_line_is_not_printed_on_success(with_context, monkeypatch, capsys):
    with_context(ONLINE)
    monkeypatch.setattr(
        _cli_io, "send_command_reverse",
        lambda method, params=None, timeout=15: {"ok": True, "data": {"status": "pong"}},
    )
    _cli_io.cmd_daemon("ping", {}, output_fmt="json")
    assert capsys.readouterr().err == ""

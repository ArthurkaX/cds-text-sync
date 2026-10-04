# -*- coding: utf-8 -*-
"""Tests for ``cts plc-log``: CTS line parsing and the command handler.

The parser is pure and is tested directly; the handler is tested against a
faked reverse pipe so the daemon's listing/tail/save behaviour can be driven
without CODESYS. The fixture log mixes real runtime noise with valid and
malformed ``CTS|`` lines and mirrors a real codesyscontrol.log header/line
format (``<ts>, <cmpId>, <classId>, <errorId>, <infoId>, <message>``).
"""

import argparse
import json
import os
import shutil
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_cli import _cli_handlers_plc_log as h
from cds_cli import plc_log as p

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "plc_log", "codesyscontrol.log")

# The fixture holds 11 CTS lines: 6 valid and 5 malformed.
_TOTAL = 11
_MALFORMED = 5


def _fixture_lines():
    with open(_FIXTURE, "r", encoding="utf-8") as handle:
        return handle.read().splitlines()


def _args(**kwargs):
    kwargs.setdefault("command", "plc-log")
    kwargs.setdefault("file", "codesyscontrol.log")
    kwargs.setdefault("tail", 0)
    kwargs.setdefault("log_output", "")
    kwargs.setdefault("cts", False)
    kwargs.setdefault("level", "")
    kwargs.setdefault("code", "")
    kwargs.setdefault("timeout", None)
    return argparse.Namespace(**kwargs)


class _FakeDaemon:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, method, params=None, timeout=None):
        self.calls.append((method, dict(params or {})))
        response = self.responses.get(method)
        if callable(response):
            return response(params or {})
        if response is None:
            return {"ok": True, "data": {}}
        return response


@pytest.fixture
def daemon(monkeypatch):
    fake = _FakeDaemon()
    monkeypatch.setattr(h, "send_command_reverse", fake)
    monkeypatch.setattr(h, "_daemon_timeout", lambda *a, **k: 15)
    return fake


def _payload(capsys):
    return json.loads(capsys.readouterr().out)


# -- pure parsing -------------------------------------------------------------


def test_parse_valid_line_extracts_every_field():
    record = p.parse_cts_line(
        "2026-04-22T18:23:48.001Z, 0x00000001, 1, 1, 0, "
        "CTS|M|ALM_RAISE|P1_OVERLOAD|I=12.4;LT1=78"
    )
    assert record == {
        "time": "2026-04-22T18:23:48.001Z",
        "level": "M",
        "code": "ALM_RAISE",
        "tag": "P1_OVERLOAD",
        "fields": {"I": "12.4", "LT1": "78"},
        "raw": (
            "2026-04-22T18:23:48.001Z, 0x00000001, 1, 1, 0, "
            "CTS|M|ALM_RAISE|P1_OVERLOAD|I=12.4;LT1=78"
        ),
    }


def test_non_cts_line_is_ignored():
    assert p.parse_cts_line("2026-04-22T18:23:47.110Z, 0x00008005, 1, 1, 0, SAC -> FSC") is None


def test_marker_may_sit_anywhere_and_timestamp_may_be_absent():
    wrapped = p.parse_cts_line("2026-04-22T18:23:48.005Z, 1, 1, 1, 0, prefix CTS|M|MSG|T2|x=1")
    assert wrapped["code"] == "MSG"
    assert wrapped["time"] == "2026-04-22T18:23:48.005Z"

    bare = p.parse_cts_line("CTS|V|DBG_NO_TS|P3|k=v")
    assert bare["time"] == ""
    assert bare["level"] == "V"


def test_empty_tag_and_no_payload():
    record = p.parse_cts_line("2026-04-22T18:23:48.003Z, 1, 1, 1, 0, CTS|M|ALM_CLEAR|")
    assert record["tag"] == ""
    assert record["fields"] == {}


@pytest.mark.parametrize(
    "line, reason",
    [
        ("CTS|X|BAD_LEVEL|T1", "level"),
        ("CTS|M|bad_code|T1", "code"),
        ("CTS|M|ALM_RAISE|T1|novalue", "no '='"),
        ("CTS|M|ALM_RAISE|T1|K=1|bad", "contains '|'"),
        ("CTS|", "missing level/code"),
    ],
)
def test_malformed_line_is_kept_with_a_reason(line, reason):
    record = p.parse_cts_line(line)
    assert record is not None
    assert reason in record["parse_error"]


def test_parse_lines_keeps_only_cts_records():
    records = p.parse_cts_lines(_fixture_lines())
    assert len(records) == _TOTAL


def test_filter_keeps_malformed_records_visible():
    records = p.parse_cts_lines(_fixture_lines())
    # A malformed record survives every filter -- that is what parse_error is
    # for -- while the well-formed records follow the filter.
    kept = p.filter_records(records, code="ALM_RAISE")
    assert [r["code"] for r in kept if not r.get("parse_error")] == [
        "ALM_RAISE",
        "ALM_RAISE",
    ]
    assert sum(1 for r in kept if r.get("parse_error")) == _MALFORMED

    assert len(p.filter_records(records, level="M")) == 4 + _MALFORMED
    assert len(p.filter_records(records, level="V")) == 2 + _MALFORMED
    assert len(p.filter_records(records, code="DBG_STEP")) == 1 + _MALFORMED


# -- handler ------------------------------------------------------------------


def test_returns_false_for_another_command(daemon):
    assert h.dispatch_plc_log(_args(command="status")) is False


def test_no_options_lists_log_files(daemon, capsys):
    daemon.responses["plc_log"] = {
        "ok": True,
        "data": {"log_files": [{"name": "codesyscontrol.log"}], "count": 1},
    }
    assert h.dispatch_plc_log(_args()) is True
    assert daemon.calls == [("plc_log", {"file": "codesyscontrol.log"})]
    assert _payload(capsys)["count"] == 1


def test_file_and_tail_pass_through(daemon, capsys):
    daemon.responses["plc_log"] = {"ok": True, "data": {"tail": ["a", "b"], "tail_count": 2}}
    h.dispatch_plc_log(_args(file="other.log", tail=50))
    assert daemon.calls == [("plc_log", {"file": "other.log", "tail": "50"})]
    assert _payload(capsys)["tail"] == ["a", "b"]


def test_not_connected_error_passes_through(daemon, capsys):
    daemon.responses["plc_log"] = {
        "ok": False,
        "error": "Not connected. Call connect_to_device first.",
    }
    with pytest.raises(SystemExit) as exc:
        h.dispatch_plc_log(_args())
    assert exc.value.code == 1
    assert "Not connected" in capsys.readouterr().err


def test_output_is_saved_and_reported(daemon, capsys):
    daemon.responses["plc_log"] = {
        "ok": True,
        "data": {"file": "codesyscontrol.log", "saved_to": "C:/Temp/codesyscontrol.log"},
    }
    h.dispatch_plc_log(_args(log_output="C:/Temp"))
    assert daemon.calls == [
        ("plc_log", {"file": "codesyscontrol.log", "output": "C:/Temp"})
    ]
    assert _payload(capsys)["saved_to"] == "C:/Temp/codesyscontrol.log"


def test_cts_parses_the_tail(daemon, capsys):
    daemon.responses["plc_log"] = {"ok": True, "data": {"tail": _fixture_lines()}}
    assert h.dispatch_plc_log(_args(cts=True, tail=200)) is True

    payload = _payload(capsys)
    assert payload["source"] == "tail"
    assert payload["count"] == _TOTAL
    assert payload["parse_errors"] == _MALFORMED
    assert payload["records"][0]["code"] == "ALM_RAISE"


def test_cts_full_log_uses_a_scratch_folder(daemon, monkeypatch, tmp_path, capsys):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(h.tempfile, "mkdtemp", lambda prefix="": str(scratch))

    def respond(params):
        assert params["output"] == str(scratch)
        shutil.copyfile(_FIXTURE, scratch / "codesyscontrol.log")
        return {"ok": True, "data": {"saved_to": str(scratch / "codesyscontrol.log")}}

    daemon.responses["plc_log"] = respond
    h.dispatch_plc_log(_args(cts=True))

    payload = _payload(capsys)
    assert payload["source"] == "file"
    assert payload["count"] == _TOTAL
    assert not scratch.exists()  # the scratch folder is not left behind


def test_cts_with_output_reads_the_saved_file(daemon, capsys):
    daemon.responses["plc_log"] = {
        "ok": True,
        "data": {"saved_to": _FIXTURE},
    }
    h.dispatch_plc_log(_args(cts=True, log_output="C:/Temp"))
    payload = _payload(capsys)
    assert payload["count"] == _TOTAL
    assert payload["saved_to"] == _FIXTURE


def test_level_implies_cts(daemon, capsys):
    daemon.responses["plc_log"] = {"ok": True, "data": {"tail": _fixture_lines()}}
    h.dispatch_plc_log(_args(level="V", tail=200))
    payload = _payload(capsys)
    assert payload["count"] == 2 + _MALFORMED


def test_code_implies_cts(daemon, capsys):
    daemon.responses["plc_log"] = {"ok": True, "data": {"tail": _fixture_lines()}}
    h.dispatch_plc_log(_args(code="DBG_STEP", tail=200))
    payload = _payload(capsys)
    assert payload["count"] == 1 + _MALFORMED
    # The one well-formed match comes first (file order); malformed records
    # are appended because they are never filtered out.
    assert payload["records"][0]["code"] == "DBG_STEP"
    assert payload["parse_errors"] == _MALFORMED


def test_cts_without_a_saved_file_errors(daemon, capsys):
    daemon.responses["plc_log"] = {"ok": True, "data": {}}
    with pytest.raises(SystemExit) as exc:
        h.dispatch_plc_log(_args(cts=True, log_output="C:/Temp"))
    assert exc.value.code == 1
    assert "saved" in capsys.readouterr().err

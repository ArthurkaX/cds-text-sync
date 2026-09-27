# -*- coding: utf-8 -*-
"""
test_pipe_targets.py — Unit tests for target selection and hello handshake parsing.
"""

import pytest

from cds_text_sync.engine.pipe_targets import (
    LEGACY,
    Hello,
    TargetError,
    decide,
    format_ambiguous,
    match_project,
    parse_target,
)


class TestParseTarget:
    def test_parse_valid_string_with_prefix(self):
        assert parse_target("ide-3684") == 3684
        assert parse_target("IDE-12") == 12

    def test_parse_valid_digits_only(self):
        assert parse_target("3684") == 3684
        assert parse_target(3684) == 3684

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="expected 'ide-<pid>' or integer PID"):
            parse_target("vko")

        with pytest.raises(ValueError, match="expected 'ide-<pid>' or integer PID"):
            parse_target("ide-abc")

        with pytest.raises(ValueError, match="Target cannot be empty"):
            parse_target("")

        with pytest.raises(ValueError):
            parse_target(-5)


class TestMatchProject:
    def test_match_by_name(self):
        prj = {"name": "VKO", "path": r"S:\Projects\VKO\VKO.project", "sync_folder": r"S:\Active\VKO"}
        assert match_project(prj, "VKO") is True
        assert match_project(prj, "vko") is True
        assert match_project(prj, "VKO.project") is True
        assert match_project(prj, "vko.project") is True
        assert match_project(prj, "Other") is False

    def test_match_by_path(self):
        prj = {"name": "VKO", "path": r"S:\Projects\VKO\VKO.project", "sync_folder": r"S:\Active\VKO"}
        assert match_project(prj, r"S:\Projects\VKO\VKO.project") is True
        assert match_project(prj, "S:/Projects/VKO/VKO.project") is True
        assert match_project(prj, "s:/projects/vko/vko.project") is True
        assert match_project(prj, "S:/Projects/Other/Other.project") is False

    def test_match_none_or_empty(self):
        assert match_project(None, "VKO") is False
        assert match_project({}, "VKO") is False
        assert match_project({"name": "VKO"}, "") is False


class TestDecide:
    def test_targeted_found(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100, version="3.2.0")
        h2 = Hello(protocol=2, id="ide-200", pid=200, version="3.2.0")
        hellos = {100: h1, 200: h2}

        res = decide(hellos, target_pid=200, window_over=False)
        assert res.kind == "send"
        assert res.target == h2

    def test_targeted_not_found_window_not_over(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100, version="3.2.0")
        hellos = {100: h1}

        res = decide(hellos, target_pid=200, window_over=False)
        assert res.kind == "wait"

    def test_targeted_not_found_window_over(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100, version="3.2.0")
        hellos = {100: h1}

        res = decide(hellos, target_pid=200, window_over=True)
        assert res.kind == "error"
        assert isinstance(res.error, TargetError)
        assert res.error.code == "unknown_target"
        assert "ide-200 not found" in str(res.error)
        assert "ide-100" in str(res.error)

    def test_targeted_not_found_empty_window_over(self):
        res = decide({}, target_pid=200, window_over=True)
        assert res.kind == "error"
        assert res.error.code == "unknown_target"
        assert "no IDE answered" in str(res.error)

    def test_protocol_mismatch(self):
        h1 = Hello(protocol=1, id="ide-100", pid=100, version="3.1.0")
        hellos = {100: h1}

        res = decide(hellos, target_pid=100, window_over=False)
        assert res.kind == "error"
        assert res.error.code == "protocol_mismatch"
        assert "daemon protocol 1 != client protocol 2" in str(res.error)

    def test_untargeted_window_not_over(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100)
        hellos = {100: h1}

        res = decide(hellos, target_pid=None, window_over=False)
        assert res.kind == "wait"

    def test_untargeted_single_hello_no_extra(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100)
        hellos = {100: h1}

        res = decide(hellos, codesys_pids={100}, window_over=True)
        assert res.kind == "send"
        assert res.target == h1

    def test_untargeted_single_hello_slow_poller_extra_codesys_pid(self):
        # 1 hello received, but tasklist shows 2 CODESYS.exe processes running
        h1 = Hello(protocol=2, id="ide-100", pid=100, project={"name": "VKO"})
        hellos = {100: h1}

        res = decide(hellos, codesys_pids={100, 200}, window_over=True)
        assert res.kind == "error"
        assert res.error.code == "ambiguous_target"
        assert "2 IDE instances, choose one:" in str(res.error)
        assert "cts --target ide-100 ...   # VKO" in str(res.error)
        assert "ide-200                     # daemon not answering" in str(res.error)

    def test_untargeted_multiple_hellos(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100, project={"name": "VKO"})
        h2 = Hello(protocol=2, id="ide-200", pid=200, project={"name": "Motion"})
        hellos = {100: h1, 200: h2}

        res = decide(hellos, window_over=True)
        assert res.kind == "error"
        assert res.error.code == "ambiguous_target"
        assert "2 IDE instances, choose one:" in str(res.error)
        assert "cts --target ide-100 ...   # VKO" in str(res.error)
        assert "cts --target ide-200 ...   # Motion" in str(res.error)

    def test_untargeted_legacy_only_single(self):
        res = decide({}, legacy_pids={300}, codesys_pids={300}, window_over=True)
        assert res.kind == "send"
        assert res.target == LEGACY

    def test_untargeted_legacy_plus_hello_ambiguous(self):
        h1 = Hello(protocol=2, id="ide-100", pid=100, project={"name": "VKO"})
        hellos = {100: h1}
        legacy = {300}

        res = decide(hellos, legacy_pids=legacy, window_over=True)
        assert res.kind == "error"
        assert res.error.code == "ambiguous_target"
        assert "cts --target ide-100 ...   # VKO" in str(res.error)
        assert "ide-300                     # old daemon, no id" in str(res.error)

    def test_untargeted_empty_window_over_waits_for_first(self):
        res = decide({}, window_over=True)
        assert res.kind == "wait"


class TestFormatAmbiguous:
    def test_format_with_no_project_and_unanswering(self):
        h1 = Hello(protocol=2, id="ide-1234", pid=1234, project=None)
        msg = format_ambiguous([h1], extra_pids={5678}, legacy_pids={9999})
        assert "3 IDE instances, choose one:" in msg
        assert "cts --target ide-1234 ...   # no project" in msg
        assert "ide-5678                     # daemon not answering" in msg
        assert "ide-9999                     # old daemon, no id" in msg


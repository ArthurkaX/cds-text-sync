# -*- coding: utf-8 -*-
"""
test_reverse_pipe_pid_listing.py - "I could not look" must not read as "none".

The CLI lists CODESYS.exe with tasklist to work out whether there is an IDE to
talk to. When that listing fails -- no tasklist on a non-Windows host driving a
remote IDE, a refused call -- the old code swallowed the error and returned an
empty set, which every caller read as "no CODESYS process is running" and said
so to the user. Unknown is a third answer and has to stay one.
"""

import subprocess

import pytest

from cds_text_sync.engine import reverse_pipe_client as rpc


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Each test starts with the module's process-list cache reset."""
    monkeypatch.setattr(rpc, "_cached_codesys_pids", None)
    # raising=False: the flag only exists once the listing can report "unknown",
    # so the tests read as behaviour tests rather than fixture errors.
    monkeypatch.setattr(rpc, "_codesys_pids_listed", False, raising=False)


def _tasklist(monkeypatch, stdout=None, error=None):
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "tasklist"
        if error is not None:
            raise error
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout or "", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)


class TestListing:
    def test_a_failed_listing_is_unknown_not_empty(self, monkeypatch):
        _tasklist(monkeypatch, error=FileNotFoundError("tasklist"))

        assert rpc._list_codesys_pids() is None

    def test_a_listing_that_finds_nothing_is_an_empty_set(self, monkeypatch):
        _tasklist(monkeypatch, stdout="INFO: No tasks are running which match the criteria.\n")

        assert rpc._list_codesys_pids() == set()

    def test_pids_are_parsed_out_of_the_csv(self, monkeypatch):
        _tasklist(
            monkeypatch,
            stdout='"CODESYS.exe","4242","Console","1","1,234 K"\n'
            '"CODESYS.exe","5151","Console","1","2,345 K"\n',
        )

        assert rpc._list_codesys_pids() == {4242, 5151}

    def test_the_outcome_is_cached(self, monkeypatch):
        _tasklist(monkeypatch, stdout='"CODESYS.exe","4242","Console","1","1 K"\n')
        assert rpc._list_codesys_pids() == {4242}

        def _explode(*args, **kwargs):
            raise AssertionError("tasklist was called twice")

        monkeypatch.setattr(subprocess, "run", _explode)
        assert rpc._list_codesys_pids() == {4242}


class TestTimeoutDiagnosis:
    def test_unknown_listing_does_not_claim_the_ide_is_absent(self, monkeypatch):
        monkeypatch.setattr(rpc, "_last_ide_pid", None)
        monkeypatch.setattr(rpc, "_list_codesys_pids", lambda: None)

        hint = rpc.ReversePipeClient._diagnose_ide_timeout()

        assert "Could not list CODESYS processes" in hint
        assert "No CODESYS process is running" not in hint

    def test_an_empty_listing_still_says_the_ide_is_absent(self, monkeypatch):
        monkeypatch.setattr(rpc, "_last_ide_pid", None)
        monkeypatch.setattr(rpc, "_list_codesys_pids", lambda: set())

        hint = rpc.ReversePipeClient._diagnose_ide_timeout()

        assert "No CODESYS process is running" in hint

# -*- coding: utf-8 -*-
"""Characterization grid for ``cds_cli.verify.stages.stage_build``.

``stage_build`` is the only stage of ``cts verify`` that leans on a live IDE:
it fingerprints the workspace, asks the daemon to compile, and then has to
decide whether the daemon's answer is *evidence about this workspace* -- the
payload may be missing, non-boolean, for another checkout, for another
revision of this one, or incomplete. Each of those branches turns into a
different stage status, reason and reason_code, and the CLI's exit code and
"next steps" are derived from exactly those.

The end-to-end tests in ``tests/unit/test_verify.py`` cover the common routes
through the CLI. This grid pins the whole contract of the stage itself: the
fingerprint handshake, the probe-then-build request order and their timeouts,
every payload shape that means "not evidence", the compiler-message
classification, and how the counts, summary and ``complete`` flag are built.
Boundaries are faked (daemon transport, fingerprint scan, clock); the
workspace is a real temporary directory.

Known oddities are pinned as they are and described in the task report; none
is fixed here.
"""

from __future__ import annotations

import os

import pytest

from cds_cli.verify import fingerprint as verify_fingerprint
from cds_cli.verify import model as verify_model
from cds_cli.verify import stages


STATUS_ERROR = verify_model.STATUS_ERROR
STATUS_FAIL = verify_model.STATUS_FAIL
STATUS_PASS = verify_model.STATUS_PASS
STATUS_SKIPPED = verify_model.STATUS_SKIPPED

_SHA = "a" * 64


def clean_payload(**overrides):
    """The smallest payload a healthy daemon sends back for ``build``."""
    data = {
        "application": "Device.Application",
        "errors": 0,
        "warnings": 0,
        "messages": [],
    }
    data.update(overrides)
    return {"ok": True, "data": data}


def compiler_error(text="cannot convert INT to STRING", code="C0032", obj="PLC_PRG"):
    return {"severity": "Error", "code": code, "text": text, "object": obj}


class Harness:
    """Scripted daemon and fingerprint scan, with an ordered call log."""

    def __init__(self, monkeypatch, tmp_path):
        self.workspace = str(tmp_path)
        os.makedirs(os.path.join(self.workspace, "project-view", "POUs"), exist_ok=True)

        self.calls = []
        self.ping_response = {"ok": True}
        self.ping_raises = None
        self.build_response = clean_payload()
        self.build_raises = None
        self.fingerprint = (_SHA, True, [])

        monkeypatch.setattr(stages, "send_command_reverse", self._send)
        monkeypatch.setattr(
            verify_fingerprint, "workspace_fingerprint", self._scan
        )
        self.ctx = stages.VerifyContext(sync_folder=self.workspace)

    # -- boundaries --------------------------------------------------------

    def _send(self, method, params=None, timeout=None):
        self.calls.append((method, params, timeout))
        if method == "ping":
            if self.ping_raises is not None:
                raise self.ping_raises
            return self.ping_response
        if method == "build":
            if self.build_raises is not None:
                raise self.build_raises
            return self.build_response
        raise AssertionError("unexpected daemon method {0!r}".format(method))

    def _scan(self, root):
        self.scanned = root
        return self.fingerprint

    # -- helpers -----------------------------------------------------------

    def methods(self):
        return [call[0] for call in self.calls]

    def build_call(self):
        for method, params, timeout in self.calls:
            if method == "build":
                return params, timeout
        raise AssertionError("no build request was sent: {0}".format(self.calls))

    def run(self):
        return stages.stage_build(self.ctx)


@pytest.fixture
def build(monkeypatch, tmp_path):
    return Harness(monkeypatch, tmp_path)


# -- the fingerprint handshake -------------------------------------------------


class TestFingerprintHandshake:
    def test_a_complete_scan_sends_the_expected_fingerprint(self, build):
        build.fingerprint = (_SHA, True, [])

        result = build.run()

        params, timeout = build.build_call()
        assert params == {"workspace_fingerprint": _SHA}
        assert timeout == 120  # the default when --build-timeout is not given
        assert result.status == STATUS_PASS

    def test_an_incomplete_scan_sends_no_fingerprint_at_all(self, build):
        build.fingerprint = (_SHA, False, ["gone.st: no such file"])

        build.run()

        params, _timeout = build.build_call()
        assert params == {}

    def test_the_scan_runs_against_the_context_sync_folder(self, build):
        build.run()

        assert build.scanned == build.workspace

    def test_a_custom_build_timeout_reaches_the_daemon(self, build):
        build.ctx.build_timeout = 7.5

        build.run()

        _params, timeout = build.build_call()
        assert timeout == 7.5

    def test_an_incomplete_scan_is_reported_in_the_summary(self, build):
        build.fingerprint = (_SHA, False, ["a.st: denied", "b.st: denied"])

        result = build.run()

        assert result.summary["workspace_fingerprint_complete"] is False
        assert result.summary["workspace_fingerprint_errors"] == 2
        # The scan being incomplete does not by itself make the stage incomplete.
        assert result.complete is True
        assert result.status == STATUS_PASS

    def test_a_complete_scan_does_not_mention_completeness_in_the_summary(self, build):
        result = build.run()

        assert "workspace_fingerprint_complete" not in result.summary
        assert "workspace_fingerprint_errors" not in result.summary

    def test_the_daemon_is_probed_before_the_build_is_requested(self, build):
        build.run()

        assert build.methods() == ["ping", "build"]

    def test_the_probe_uses_the_context_probe_timeout(self, build):
        build.ctx.probe_timeout = 0.25

        build.run()

        assert build.calls[0] == ("ping", {}, 0.25)


# -- daemon availability -------------------------------------------------------


class TestDaemonAvailability:
    def test_a_dead_daemon_skips_the_stage_and_sends_no_build(self, build):
        build.ping_raises = RuntimeError("pipe not found\nsecond line")

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason_code == "daemon_unavailable"
        assert result.reason == "daemon not responding (2.0s probe): pipe not found"
        assert build.methods() == ["ping"]

    def test_a_daemon_that_refuses_the_probe_is_unavailable_with_its_reason(self, build):
        build.ping_response = {"ok": False, "error": "daemon is shutting down"}

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason_code == "daemon_unavailable"
        assert result.reason == "daemon is shutting down"

    def test_a_probe_refusal_without_a_reason_uses_the_default_text(self, build):
        build.ping_response = {"ok": False}

        result = build.run()

        assert result.reason == "daemon answered but not ok"

    def test_a_daemon_that_dies_during_the_build_skips_with_a_timeout_reason(self, build):
        build.build_raises = RuntimeError("Timeout (120s) waiting for IDE\nmore detail")

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason_code == "daemon_timeout"
        assert result.reason == (
            "daemon stopped responding during build: Timeout (120s) waiting for IDE"
        )
        assert build.methods() == ["ping", "build"]

    def test_the_probe_answer_is_cached_for_the_whole_context(self, build):
        build.run()
        build.run()

        assert build.methods().count("ping") == 1

    def test_a_long_probe_reason_is_capped_to_its_first_line(self, build):
        build.ping_raises = RuntimeError("head\n" + "x" * 500)

        result = build.run()

        assert result.reason == "daemon not responding (2.0s probe): head"


# -- payload shapes that are not evidence --------------------------------------


class TestPayloadRejections:
    def test_a_non_object_response_is_an_error(self, build):
        build.build_response = ["not", "a", "dict"]

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == "daemon returned a non-object response"
        assert result.reason_code == "tool_error"  # the errored() default

    def test_a_refusal_without_a_payload_is_an_error_carrying_the_daemon_text(self, build):
        build.build_response = {"ok": False, "error": "no project open"}

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == "no project open"
        assert result.reason_code == "daemon_refused"

    def test_a_refusal_without_a_payload_or_a_reason_uses_the_default(self, build):
        build.build_response = {"ok": False}

        result = build.run()

        assert result.reason == "build refused"
        assert result.reason_code == "daemon_refused"

    def test_success_without_a_payload_is_an_error(self, build):
        build.build_response = {"ok": True}

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == "daemon returned no build payload"
        assert result.reason_code == "invalid_payload"

    def test_a_payload_that_is_not_a_dict_is_an_error(self, build):
        build.build_response = {"ok": True, "data": "compiled fine, honest"}

        result = build.run()

        assert result.reason == "daemon returned no build payload"
        assert result.reason_code == "invalid_payload"

    def test_a_refusal_that_carries_a_real_report_is_compiler_evidence(self, build):
        build.build_response = {
            "ok": False,
            "error": "build failed",
            "data": {"application": "App", "errors": 1, "warnings": 0, "messages": []},
        }

        result = build.run()

        assert result.status == STATUS_FAIL
        assert result.summary["errors"] == 1


# -- identity: which workspace was compiled ------------------------------------


class TestWorkspaceIdentity:
    def test_a_report_from_another_sync_folder_is_stale(self, build):
        build.build_response = clean_payload(
            sync_folder=os.path.join(build.workspace, "other-checkout")
        )

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason == "IDE sync-folder does not match the requested workspace"
        assert result.reason_code == "stale_ide"

    def test_a_matching_sync_folder_is_accepted(self, build):
        build.build_response = clean_payload(sync_folder=build.workspace)

        result = build.run()

        assert result.status == STATUS_PASS
        assert "sync_folder" not in result.summary

    def test_a_daemon_that_cannot_fingerprint_its_workspace_skips(self, build):
        build.fingerprint = (_SHA, True, [])
        build.build_response = clean_payload(workspace_fingerprint_complete=False)

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason == "IDE could not compute a complete workspace fingerprint"
        assert result.reason_code == "identity_unknown"

    def test_the_cannot_fingerprint_skip_only_applies_when_our_scan_completed(self, build):
        # Our own scan was incomplete, so the daemon's False is not a
        # contradiction of anything we asserted.
        build.fingerprint = (_SHA, False, ["a.st: denied"])
        build.build_response = clean_payload(workspace_fingerprint_complete=False)

        result = build.run()

        assert result.status == STATUS_PASS

    def test_a_non_boolean_completeness_flag_is_an_invalid_payload(self, build):
        build.build_response = clean_payload(workspace_fingerprint_complete="yes")

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == (
            "invalid build payload: workspace_fingerprint_complete must be boolean"
        )
        assert result.reason_code == "invalid_payload"

    def test_a_fingerprint_that_is_not_sha256_is_an_invalid_payload(self, build):
        build.build_response = clean_payload(workspace_fingerprint="abc")

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == (
            "invalid build payload: workspace_fingerprint must be SHA-256"
        )
        assert result.reason_code == "invalid_payload"

    def test_a_non_string_fingerprint_is_an_invalid_payload(self, build):
        build.build_response = clean_payload(workspace_fingerprint=12345)

        result = build.run()

        assert result.reason_code == "invalid_payload"

    def test_another_workspace_fingerprint_is_stale(self, build):
        build.build_response = clean_payload(workspace_fingerprint="b" * 64)

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason == (
            "IDE workspace fingerprint does not match the requested workspace"
        )
        assert result.reason_code == "stale_ide"

    def test_a_matching_fingerprint_lands_in_the_summary(self, build):
        build.build_response = clean_payload(workspace_fingerprint=_SHA.upper())

        result = build.run()

        assert result.status == STATUS_PASS
        assert result.summary["workspace_fingerprint"] == _SHA.upper()

    def test_a_fingerprint_is_accepted_when_our_scan_was_incomplete(self, build):
        build.fingerprint = (_SHA, False, ["a.st: denied"])
        build.build_response = clean_payload(workspace_fingerprint="b" * 64)

        result = build.run()

        assert result.status == STATUS_PASS
        assert result.summary["workspace_fingerprint"] == "b" * 64

    def test_a_stale_import_attestation_skips(self, build):
        build.build_response = clean_payload(import_freshness="stale")

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason == (
            "workspace has changed since the last successful IDE import"
        )
        assert result.reason_code == "stale_ide"
        assert result.summary == {"import_freshness": "stale"}
        assert result.complete is False

    def test_an_unknown_import_attestation_skips(self, build):
        build.build_response = clean_payload(import_freshness="unknown")

        result = build.run()

        assert result.status == STATUS_SKIPPED
        assert result.reason == "IDE import freshness could not be confirmed"
        assert result.reason_code == "identity_unknown"
        assert result.complete is False

    def test_a_verified_import_attestation_stays_in_the_summary(self, build):
        build.build_response = clean_payload(import_freshness="verified")

        result = build.run()

        assert result.status == STATUS_PASS
        assert result.summary["import_freshness"] == "verified"

    def test_an_unrecognised_import_attestation_is_an_invalid_payload(self, build):
        build.build_response = clean_payload(import_freshness="probably")

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == (
            "invalid build payload: import_freshness must be verified, stale, or unknown"
        )
        assert result.reason_code == "invalid_payload"

    def test_the_sync_folder_check_runs_before_the_other_payload_checks(self, build):
        # Both the sync folder and the completeness flag are wrong; the first
        # check in the function wins, and that is the pinned behaviour.
        build.build_response = clean_payload(
            sync_folder=os.path.join(build.workspace, "elsewhere"),
            workspace_fingerprint_complete="yes",
        )

        result = build.run()

        assert result.reason_code == "stale_ide"


# -- counts and compiler messages ----------------------------------------------


class TestCountsAndMessages:
    @pytest.mark.parametrize(
        "value", [True, False, "2", -1, None, [2]]
    )
    def test_a_bad_error_count_is_an_invalid_payload(self, build, value):
        build.build_response = clean_payload(errors=value)

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == (
            "invalid build payload: errors must be a non-negative number"
        )
        assert result.reason_code == "invalid_payload"

    def test_a_boolean_warning_count_is_an_invalid_payload(self, build):
        build.build_response = clean_payload(warnings=True)

        result = build.run()

        assert result.reason == (
            "invalid build payload: warnings must be a non-negative number"
        )

    def test_a_float_count_is_accepted_and_truncated_to_int(self, build):
        build.build_response = clean_payload(errors=2.0, warnings=3.7)

        result = build.run()

        assert result.summary["errors"] == 2
        assert result.summary["warnings"] == 3

    def test_messages_that_are_not_a_list_are_an_invalid_payload(self, build):
        build.build_response = clean_payload(messages="C0032: bad")

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == "invalid build payload: messages must be a list"
        assert result.reason_code == "invalid_payload"

    def test_missing_messages_are_treated_as_none(self, build):
        build.build_response = {"ok": True, "data": {"errors": 0, "warnings": 0}}

        result = build.run()

        assert result.status == STATUS_PASS
        assert result.problem_count == 0

    def test_only_a_severity_containing_the_word_error_becomes_a_problem(self, build):
        build.build_response = clean_payload(
            errors=1,
            messages=[
                compiler_error(text="real failure"),
                {"severity": "error", "text": "lowercase is ignored"},
                {"severity": "ERROR", "text": "shouty is ignored"},
                {"severity": "Warning", "text": "warned"},
                {"severity": "", "text": "unclassified"},
                {"severity": "Fatal Error", "text": "substring match"},
            ],
        )

        result = build.run()

        assert result.problem_count == 2
        assert [p.message for p in result.problems] == ["real failure", "substring match"]

    def test_a_message_is_mapped_onto_the_problem_fields(self, build):
        build.build_response = clean_payload(
            errors=1,
            messages=[
                {
                    "severity": "Error",
                    "code": "C0032",
                    "text": "cannot convert INT to STRING",
                    "object": "PLC_PRG",
                }
            ],
        )

        result = build.run()

        problem = result.problems[0]
        assert problem.severity == "error"  # normalised, not the daemon's "Error"
        assert problem.rule == "C0032"
        assert problem.message == "cannot convert INT to STRING"
        assert problem.where == "PLC_PRG"
        assert problem.to_dict() == {
            "message": "cannot convert INT to STRING",
            "severity": "error",
            "rule": "C0032",
            "where": "PLC_PRG",
        }

    def test_a_message_without_fields_still_becomes_an_empty_problem(self, build):
        build.build_response = clean_payload(errors=1, messages=[{"severity": "Error"}])

        result = build.run()

        assert result.problems[0].message == ""

    def test_warnings_are_counted_but_are_not_problems(self, build):
        build.build_response = clean_payload(
            errors=0,
            warnings=4,
            messages=[{"severity": "Warning", "code": "C0197", "text": "unused"}],
        )

        result = build.run()

        assert result.status == STATUS_PASS
        assert result.summary["warnings"] == 4
        assert result.problem_count == 0

    def test_a_zero_count_with_error_messages_is_corrected_to_their_number(self, build):
        build.build_response = clean_payload(
            errors=0,
            warnings=0,
            messages=[compiler_error(code="C1"), compiler_error(code="C2")],
        )

        result = build.run()

        assert result.summary["errors"] == 2
        assert result.problem_count == 2
        assert result.status == STATUS_FAIL

    def test_a_positive_count_is_not_overridden_by_the_message_list(self, build):
        build.build_response = clean_payload(
            errors=5, messages=[compiler_error()]
        )

        result = build.run()

        assert result.summary["errors"] == 5
        assert result.problem_count == 1

    def test_a_non_dict_message_makes_the_diagnostics_incomplete(self, build):
        build.build_response = clean_payload(
            errors=0,
            messages=["a bare string", None],
        )

        result = build.run()

        assert result.status == STATUS_ERROR  # incomplete, not a project failure
        assert result.reason == "compiler diagnostics are incomplete"
        assert result.reason_code == "tool_error"
        assert result.complete is False
        assert result.summary["diagnostics_complete"] is False
        assert result.problem_count == 0

    def test_a_non_dict_message_does_not_hide_a_real_failure(self, build):
        build.build_response = clean_payload(
            errors=0,
            messages=[compiler_error(), "a bare string"],
        )

        result = build.run()

        assert result.status == STATUS_FAIL  # the readable failure stands
        assert result.complete is False  # the diagnostics are still partial
        assert result.problem_count == 1
        assert result.summary["diagnostics_complete"] is False

    def test_a_complete_false_flag_from_the_daemon_makes_the_stage_incomplete(self, build):
        build.build_response = clean_payload(diagnostics_complete=False)

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == "compiler diagnostics are incomplete"
        assert result.reason_code == "tool_error"
        assert result.summary["diagnostics_complete"] is False
        assert result.complete is False

    def test_a_truthy_non_boolean_completeness_flag_is_taken_as_complete(self, build):
        # Oddity pinned as-is: the flag is coerced with bool(), so any truthy
        # value -- including the string "no" -- reads as complete.
        build.build_response = clean_payload(diagnostics_complete="no")

        result = build.run()

        assert result.status == STATUS_PASS
        assert "diagnostics_complete" not in result.summary

    def test_incomplete_diagnostics_do_not_downgrade_a_real_failure(self, build):
        build.build_response = clean_payload(errors=1, diagnostics_complete=False)

        result = build.run()

        assert result.status == STATUS_FAIL  # the failure stands
        assert result.complete is False  # but the answer is still partial
        assert result.reason == "compiler diagnostics are incomplete"

    def test_ok_false_with_no_diagnostics_at_all_is_an_invalid_payload(self, build):
        build.build_response = {
            "ok": False,
            "data": {"errors": 0, "warnings": 0, "messages": []},
        }

        result = build.run()

        assert result.status == STATUS_ERROR
        assert result.reason == (
            "daemon returned ok=false without compiler diagnostics"
        )
        assert result.reason_code == "invalid_payload"

    def test_ok_false_with_a_warning_only_is_still_an_invalid_payload(self, build):
        build.build_response = {
            "ok": False,
            "data": {
                "errors": 0,
                "warnings": 1,
                "messages": [{"severity": "Warning", "text": "unused"}],
            },
        }

        result = build.run()

        assert result.reason_code == "invalid_payload"

    def test_more_problems_than_the_cap_are_reported_with_the_full_count(self, build):
        build.build_response = clean_payload(
            errors=0,
            messages=[compiler_error(code="C{0}".format(i)) for i in range(25)],
        )

        result = build.run()

        assert result.problem_count == 25
        assert len(result.problems) == verify_model.MAX_PROBLEMS_PER_STAGE
        assert result.truncated is True
        assert result.status == STATUS_FAIL


# -- summary composition -------------------------------------------------------


class TestSummary:
    def test_the_application_and_counts_are_reported(self, build):
        build.build_response = clean_payload(
            application="Device.Application", errors=0, warnings=2
        )

        result = build.run()

        assert result.summary["application"] == "Device.Application"
        assert result.summary["errors"] == 0
        assert result.summary["warnings"] == 2

    def test_a_missing_application_is_an_empty_string(self, build):
        build.build_response = {"ok": True, "data": {"errors": 0, "warnings": 0}}

        result = build.run()

        assert result.summary["application"] == ""

    def test_elapsed_seconds_is_carried_when_present(self, build):
        build.build_response = clean_payload(elapsed_seconds=4.2)

        result = build.run()

        assert result.summary["elapsed_seconds"] == 4.2

    def test_a_zero_elapsed_time_is_still_carried(self, build):
        build.build_response = clean_payload(elapsed_seconds=0)

        result = build.run()

        assert result.summary["elapsed_seconds"] == 0

    def test_a_missing_elapsed_time_is_not_invented(self, build):
        result = build.run()

        assert "elapsed_seconds" not in result.summary

    def test_a_pass_has_no_reason_and_no_reason_code(self, build):
        result = build.run()

        assert result.status == STATUS_PASS
        assert result.reason == ""
        assert result.reason_code == ""

    def test_the_reported_dict_is_the_stage_contract(self, build):
        build.build_response = clean_payload(
            application="App",
            errors=1,
            warnings=0,
            messages=[compiler_error()],
            elapsed_seconds=1.5,
        )

        result = build.run()

        assert result.to_dict() == {
            "stage": "build",
            "status": "fail",
            "summary": {"application": "App", "errors": 1, "warnings": 0,
                        "elapsed_seconds": 1.5},
            "problems": [
                {
                    "message": "cannot convert INT to STRING",
                    "severity": "error",
                    "rule": "C0032",
                    "where": "PLC_PRG",
                }
            ],
            "problem_count": 1,
            "truncated": False,
        }

    def test_the_stage_is_named_build(self, build):
        assert build.run().stage == "build"


# -- how the registry runs it --------------------------------------------------


class TestRegistry:
    def test_build_is_a_daemon_stage_but_not_opt_in(self):
        row = next(s for s in stages.STAGES if s.name == "build")

        assert row.func is stages.stage_build
        assert row.needs_daemon is True
        assert row.opt_in is False

    def test_run_stage_stamps_a_duration(self, build, monkeypatch):
        ticks = iter([100.0, 100.25])
        monkeypatch.setattr(stages.time, "time", lambda: next(ticks))
        row = next(s for s in stages.STAGES if s.name == "build")

        result = stages.run_stage(row, build.ctx)

        assert result.duration_ms == 250

    def test_run_stage_contains_a_crash_as_an_error(self, build, monkeypatch):
        # A crash inside the scan is not caught by stage_build itself, so
        # run_stage is the boundary that has to contain it.
        def boom(root):
            raise OSError("disk fell over")

        monkeypatch.setattr(verify_fingerprint, "workspace_fingerprint", boom)
        row = next(s for s in stages.STAGES if s.name == "build")

        result = stages.run_stage(row, build.ctx)

        assert result.stage == "build"
        assert result.status == STATUS_ERROR
        assert result.reason == "OSError: disk fell over"
        assert result.reason_code == "tool_error"

    def test_build_runs_between_analyze_and_test_in_the_registry(self):
        assert stages.STAGE_NAMES == ["analyze", "visu-sketch", "build", "test"]


# -- the fingerprint module itself ---------------------------------------------


class TestRealFingerprintScan:
    """The real scan is cheap and local, so two cases exercise it directly."""

    def test_an_empty_folder_is_complete(self, tmp_path):
        digest, complete, errors = verify_fingerprint.workspace_fingerprint(str(tmp_path))

        assert complete is True
        assert errors == []
        assert len(digest) == 64

    def test_content_changes_the_digest(self, tmp_path):
        (tmp_path / "a.st").write_text("PROGRAM A\n", encoding="utf-8")
        first, _complete, _errors = verify_fingerprint.workspace_fingerprint(str(tmp_path))
        (tmp_path / "a.st").write_text("PROGRAM A2\n", encoding="utf-8")
        second, _complete, _errors = verify_fingerprint.workspace_fingerprint(str(tmp_path))

        assert first != second

    def test_an_unreadable_file_is_reported_instead_of_hashed(self, tmp_path, monkeypatch):
        (tmp_path / "a.st").write_text("PROGRAM A\n", encoding="utf-8")

        real_open = open

        def deny(path, mode="r", *args, **kwargs):
            if mode == "rb" and str(path).endswith("a.st"):
                raise OSError("permission denied")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", deny)

        _digest, complete, errors = verify_fingerprint.workspace_fingerprint(str(tmp_path))

        assert complete is False
        assert len(errors) == 1
        assert errors[0].startswith("a.st: ")

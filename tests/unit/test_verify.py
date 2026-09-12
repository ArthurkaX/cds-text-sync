"""Tests for ``cts verify`` -- the one-gate orchestrator.

The daemon is mocked at the ``send_command_reverse`` seam, the same seam
``test_cli_handlers_daemon.py`` uses. Nothing here needs a live IDE, which is
the whole point of the command.
"""

from __future__ import annotations

import json
import os

import pytest

from analyze_helpers import copy_fixture, run_cli

from cds_cli.verify import model as verify_model


# -- helpers ------------------------------------------------------------------


def _verify(workspace, extra=None, pretty=False):
    # ``--pretty`` / ``--output`` are global flags, so they precede the command.
    argv = ["--pretty"] if pretty else []
    argv += ["verify", "--sync-folder", workspace]
    argv.extend(extra or [])
    code, out, err = run_cli(argv)
    return code, out, err


def _verify_json(workspace, extra=None):
    code, out, err = _verify(workspace, extra)
    return code, json.loads(out), err


def _stage(doc, name):
    for stage in doc["stages"]:
        if stage["stage"] == name:
            return stage
    raise AssertionError(f"no stage {name!r} in {[s['stage'] for s in doc['stages']]}")


@pytest.fixture()
def workspace(tmp_path):
    """A project the analyzer has nothing to say about.

    The shared ``analyze`` fixture deliberately contains 30 findings, so it is
    the wrong base for every case that wants a clean verdict.
    """
    os.makedirs(os.path.join(str(tmp_path), "project-view", "POUs"))
    return str(tmp_path)


@pytest.fixture()
def findings_workspace(tmp_path):
    """The shared analyze fixture -- known to produce findings."""
    return copy_fixture(str(tmp_path))


@pytest.fixture()
def dead_daemon(monkeypatch):
    """Every transport call raises, as it does when no IDE is running."""

    def _boom(method, params=None, timeout=None, **kwargs):
        raise RuntimeError(
            "pipe not found\nlong second line the report should not carry"
        )

    # ``stages`` imports the function by name, so this is the seam that counts.
    monkeypatch.setattr("cds_cli.verify.stages.send_command_reverse", _boom)
    return _boom


def _fake_daemon(monkeypatch, responses):
    """Answer ``ping`` alive and every other method from *responses*."""
    seen = []

    def _send(method, params=None, timeout=None, **kwargs):
        seen.append((method, params))
        if method == "ping":
            return {"ok": True}
        if method not in responses:
            raise AssertionError(f"unexpected daemon method {method!r}")
        return responses[method]

    monkeypatch.setattr("cds_cli.verify.stages.send_command_reverse", _send)
    return seen


# -- starting up --------------------------------------------------------------


def test_missing_project_view_is_exit_2(tmp_path):
    code, out, err = _verify(str(tmp_path))
    assert code == 2
    assert "project-view" in err
    assert out == ""


def test_missing_folder_is_exit_2(tmp_path):
    code, _out, err = _verify(str(tmp_path / "nope"))
    assert code == 2
    assert "No such folder" in err


def test_project_view_itself_is_accepted(workspace, dead_daemon):
    code, doc, _err = _verify_json(os.path.join(workspace, "project-view"))
    assert code == 0
    assert doc["sync_folder"] == os.path.abspath(workspace)


def test_unknown_stage_is_exit_2(workspace):
    code, _out, err = _verify(workspace, ["--only", "analyse"])
    assert code == 2
    assert "analyse" in err
    assert "analyze" in err


def test_empty_only_selection_is_exit_2(workspace):
    code, _out, err = _verify(workspace, ["--only", ","])
    assert code == 2
    assert "at least one stage" in err


# -- the offline stages -------------------------------------------------------


def test_clean_project_passes_offline(workspace, dead_daemon):
    code, doc, _err = _verify_json(workspace, ["--only", "analyze"])
    assert code == 0
    assert doc["verdict"] == "pass"
    assert doc["complete"] is True
    assert [s["stage"] for s in doc["stages"]] == ["analyze"]
    assert _stage(doc, "analyze")["status"] == "pass"


def test_findings_fail_the_gate(findings_workspace, dead_daemon):
    code, doc, _err = _verify_json(findings_workspace, ["--only", "analyze"])
    stage = _stage(doc, "analyze")
    assert stage["status"] == "fail"
    assert stage["summary"]["findings"] > 0
    assert doc["verdict"] == "fail"
    assert any("cts analyze" in step for step in doc["next"])
    assert code == 1


def test_fail_on_raises_the_bar(findings_workspace, dead_daemon):
    # The fixture has style/suspicious findings but nothing at danger.
    code, doc, _err = _verify_json(
        findings_workspace, ["--only", "analyze", "--fail-on", "danger"]
    )
    stage = _stage(doc, "analyze")
    assert stage["status"] == "pass"
    assert stage["summary"]["fail_on"] == "danger"
    assert stage["summary"]["findings"] > 0
    assert doc["verdict"] == "pass"
    assert code == 0


def test_findings_are_capped(findings_workspace, dead_daemon):
    cap = verify_model.MAX_PROBLEMS_PER_STAGE
    _code, doc, _err = _verify_json(findings_workspace, ["--only", "analyze"])
    stage = _stage(doc, "analyze")
    assert stage["problem_count"] > cap
    assert len(stage["problems"]) == cap
    assert stage["truncated"] is True


def test_sketchless_project_skips_the_sketch_stage(workspace, dead_daemon):
    code, doc, _err = _verify_json(workspace, ["--only", "visu-sketch"])
    stage = _stage(doc, "visu-sketch")
    assert stage["status"] == "skipped"
    assert ".visu" in stage["reason"]
    # Nothing to check is not a failure.
    assert doc["verdict"] == "pass"
    assert doc["complete"] is False
    assert code == 0


def test_unreadable_sketch_is_a_real_problem(workspace, dead_daemon):
    sketch_dir = os.path.join(workspace, ".visu")
    os.makedirs(sketch_dir, exist_ok=True)
    with open(os.path.join(sketch_dir, "Broken.svg"), "w", encoding="utf-8") as handle:
        handle.write("<svg><rect")

    code, doc, _err = _verify_json(workspace, ["--only", "visu-sketch"])
    stage = _stage(doc, "visu-sketch")
    assert stage["status"] == "fail"
    assert stage["summary"]["unreadable"] == 1
    assert code == 1


def test_previews_are_not_linted(workspace, dead_daemon):
    sketch_dir = os.path.join(workspace, ".visu")
    os.makedirs(sketch_dir, exist_ok=True)
    with open(
        os.path.join(sketch_dir, "Screen.preview.svg"), "w", encoding="utf-8"
    ) as handle:
        handle.write("<svg><rect")

    _code, doc, _err = _verify_json(workspace, ["--only", "visu-sketch"])
    # The only SVG present is a generated preview, so there is nothing to lint.
    assert _stage(doc, "visu-sketch")["status"] == "skipped"


# -- the daemon stages --------------------------------------------------------


def test_dead_daemon_skips_build_without_failing(workspace, dead_daemon):
    code, doc, err = _verify_json(workspace, ["--only", "analyze,build"])
    build = _stage(doc, "build")
    assert build["status"] == "skipped"
    assert "daemon" in build["reason"]
    # The transport raises a multi-line diagnostic; the report keeps one line.
    assert "\n" not in build["reason"]
    assert "long second line" not in build["reason"]
    assert doc["verdict"] == "pass"
    assert doc["complete"] is False
    assert code == 0
    assert "--incomplete error" in err


def test_incomplete_error_turns_a_skip_into_exit_3(workspace, dead_daemon):
    code, doc, _err = _verify_json(
        workspace, ["--only", "analyze,build", "--incomplete", "error"]
    )
    assert doc["complete"] is False
    assert doc["exit_code"] == 3
    assert code == 3


def test_compiler_errors_are_a_fail(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": False,
                "data": {
                    "application": "Device.Application",
                    "errors": 2,
                    "warnings": 1,
                    "elapsed_seconds": 4.2,
                    "messages": [
                        {
                            "severity": "Error",
                            "code": "C0032",
                            "text": "cannot convert INT to STRING",
                            "object": "PLC_PRG",
                        },
                        {
                            "severity": "Warning",
                            "code": "C0197",
                            "text": "unused variable",
                            "object": "PLC_PRG",
                        },
                    ],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "fail"
    assert build["summary"]["errors"] == 2
    # Warnings are reported in the summary but are not problems.
    assert build["problem_count"] == 1
    assert build["problems"][0]["rule"] == "C0032"
    assert doc["verdict"] == "fail"
    # A real compile failure is a complete answer, not an incomplete one.
    assert doc["complete"] is True
    assert code == 1


def test_daemon_refusal_is_error_not_fail(workspace, monkeypatch):
    _fake_daemon(monkeypatch, {"build": {"ok": False, "error": "no project open"}})

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "error"
    assert build["reason"] == "no project open"
    # Nothing was verified, so the project is not blamed.
    assert doc["verdict"] == "pass"
    assert doc["complete"] is False
    assert code == 0


def test_clean_build_passes(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {
                    "application": "Device.Application",
                    "errors": 0,
                    "warnings": 0,
                    "messages": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    assert _stage(doc, "build")["status"] == "pass"
    assert code == 0


def test_build_errors_override_inconsistent_transport_ok(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {"errors": 1, "warnings": 0, "messages": []},
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "fail"
    assert build["summary"]["errors"] == 1
    assert code == 1


def test_build_from_another_sync_folder_is_not_credited(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {
                    "sync_folder": os.path.join(workspace, "other-checkout"),
                    "errors": 0,
                    "warnings": 0,
                    "messages": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "skipped"
    assert build["reason_code"] == "stale_ide"
    assert doc["complete"] is False
    assert code == 0


def test_build_with_another_workspace_fingerprint_is_not_credited(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {
                    "sync_folder": workspace,
                    "workspace_fingerprint": "0" * 64,
                    "errors": 0,
                    "warnings": 0,
                    "messages": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "skipped"
    assert build["reason_code"] == "stale_ide"
    assert doc["complete"] is False
    assert code == 0


def test_incomplete_workspace_fingerprint_is_not_credited(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {
                    "sync_folder": workspace,
                    "workspace_fingerprint_complete": False,
                    "errors": 0,
                    "warnings": 0,
                    "messages": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "skipped"
    assert build["reason_code"] == "identity_unknown"
    assert doc["complete"] is False
    assert code == 0


def test_build_without_import_attestation_is_not_credited(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {
                    "sync_folder": workspace,
                    "import_freshness": "unknown",
                    "errors": 0,
                    "warnings": 0,
                    "messages": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "skipped"
    assert build["reason_code"] == "identity_unknown"
    assert doc["complete"] is False
    assert code == 0


def test_stale_import_attestation_is_not_credited(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": True,
                "data": {
                    "sync_folder": workspace,
                    "import_freshness": "stale",
                    "errors": 0,
                    "warnings": 0,
                    "messages": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert build["status"] == "skipped"
    assert build["reason_code"] == "stale_ide"
    assert doc["complete"] is False
    assert code == 0


def test_daemon_is_probed_once_for_two_stages(workspace, monkeypatch):
    seen = _fake_daemon(
        monkeypatch,
        {
            "build": {"ok": True, "data": {"errors": 0, "warnings": 0}},
            "cicd": {
                "ok": True,
                "data": {"status": "SUCCESS", "summary": {"ok": 3, "not_ok": 0}},
            },
        },
    )

    code, _doc, _err = _verify_json(workspace, ["--only", "build,test"])
    assert code == 0
    assert [m for m, _p in seen].count("ping") == 1


# -- test stage ---------------------------------------------------------------


def test_test_stage_is_opt_in(workspace, dead_daemon):
    _code, doc, _err = _verify_json(workspace)
    names = [s["stage"] for s in doc["stages"]]
    assert "test" not in names
    assert names == ["analyze", "visu-sketch", "build"]
    assert any("--with-test" in step for step in doc["next"])


def test_failing_tests_fail_the_gate(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "cicd": {
                "ok": False,
                "data": {
                    "status": "FAIL",
                    "summary": {"ok": 1, "not_ok": 1, "total": 2},
                    "results": [
                        {
                            "file": "plans/pump.json",
                            "tests": [
                                {"status": "PASS", "name": "starts"},
                                {
                                    "status": "FAIL",
                                    "name": "stops",
                                    "message": "expected FALSE, got TRUE",
                                },
                            ],
                        }
                    ],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "test"])
    stage = _stage(doc, "test")
    assert stage["status"] == "fail"
    assert stage["problem_count"] == 1
    assert "expected FALSE" in stage["problems"][0]["message"]
    assert code == 1


def test_nested_cicd_failure_is_not_hidden_by_transport_ok(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "cicd": {
                "ok": True,
                "data": {
                    "status": "FAIL",
                    "ok": False,
                    "summary": {"ok": 0, "not_ok": 1, "total": 1},
                    "results": [],
                },
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "test"])
    stage = _stage(doc, "test")
    assert stage["status"] == "fail"
    assert stage["problem_count"] == 1
    assert code == 1


def test_invalid_cicd_payload_is_incomplete_error(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {"cicd": {"ok": True, "data": {"status": "SUCCESS", "results": "bad"}}},
    )

    code, doc, _err = _verify_json(workspace, ["--only", "test"])
    stage = _stage(doc, "test")
    assert stage["status"] == "error"
    assert stage["reason_code"] == "invalid_payload"
    assert doc["complete"] is False
    assert code == 0


def test_test_is_skipped_when_selected_build_failed(workspace, monkeypatch):
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": False,
                "data": {"errors": 1, "warnings": 0, "messages": []},
            },
            "cicd": {"ok": True, "data": {"status": "SUCCESS"}},
        },
    )

    _code, doc, _err = _verify_json(workspace, ["--only", "build,test"])
    test = _stage(doc, "test")
    assert test["status"] == "skipped"
    assert test["reason_code"] == "dependency_failed"


def test_with_test_adds_the_stage(workspace, dead_daemon):
    _code, doc, _err = _verify_json(workspace, ["--with-test"])
    assert [s["stage"] for s in doc["stages"]] == [
        "analyze",
        "visu-sketch",
        "build",
        "test",
    ]


# -- report shape -------------------------------------------------------------


def test_only_runs_in_registry_order_not_typed_order(workspace, dead_daemon):
    _code, doc, _err = _verify_json(workspace, ["--only", "build,analyze"])
    assert [s["stage"] for s in doc["stages"]] == ["analyze", "build"]


def test_problems_are_capped(workspace, monkeypatch):
    cap = verify_model.MAX_PROBLEMS_PER_STAGE
    messages = [
        {
            "severity": "Error",
            "code": f"C{index:04d}",
            "text": f"error number {index}",
            "object": "PLC_PRG",
        }
        for index in range(cap + 5)
    ]
    _fake_daemon(
        monkeypatch,
        {
            "build": {
                "ok": False,
                "data": {"errors": len(messages), "warnings": 0, "messages": messages},
            }
        },
    )

    code, doc, _err = _verify_json(workspace, ["--only", "build"])
    build = _stage(doc, "build")
    assert len(build["problems"]) == cap
    assert build["problem_count"] == cap + 5
    assert build["truncated"] is True
    assert code == 1


def test_text_output_is_readable(workspace, dead_daemon):
    code, out, _err = _verify(workspace, ["--only", "analyze,build"], pretty=True)
    assert code == 0
    assert "[PASS] analyze" in out
    assert "[SKIPPED] build" in out
    assert "verdict: pass (incomplete" in out
    assert "next:" in out


def test_schema_version_is_reported(workspace, dead_daemon):
    _code, doc, _err = _verify_json(workspace, ["--only", "analyze"])
    assert doc["schema_version"] == verify_model.SCHEMA_VERSION
    assert doc["exit_code"] == 0


def test_a_crashing_stage_does_not_sink_the_run(workspace, monkeypatch, dead_daemon):
    def _boom(ctx):
        raise ValueError("stage is broken")

    monkeypatch.setattr("cds_cli.verify.stages.stage_analyze", _boom)
    # The registry holds a reference to the original function, so patch it too.
    from cds_cli.verify import stages as verify_stages

    monkeypatch.setattr(verify_stages.STAGES[0], "func", _boom)

    code, doc, _err = _verify_json(workspace, ["--only", "analyze"])
    stage = _stage(doc, "analyze")
    assert stage["status"] == "error"
    assert "ValueError: stage is broken" in stage["reason"]
    assert doc["verdict"] == "pass"
    assert code == 0

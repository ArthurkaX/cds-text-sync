"""
test_analyze_history.py - CTS0004 against a real (tmp) git repository and
the no-git diagnostic path.
"""

import os
import shutil
import subprocess

import pytest

from analyze_helpers import copy_fixture, run_analyze_json

_WHICH_GIT = shutil.which("git")


@pytest.fixture
def git_workspace(tmp_path):
    if not _WHICH_GIT:
        pytest.skip("git not available")
    root = str(tmp_path / "sync")
    copy_fixture(root)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return root


def _reorder_persistent(root):
    path = os.path.join(root, "project-view", "POUs", "GVL_Persistent.st")
    lines = open(path, encoding="utf-8").read().split("\n")
    idx = next(i for i, line in enumerate(lines) if "p_nShift" in line)
    shift = lines.pop(idx)
    for i, line in enumerate(lines):
        if line.strip().startswith("VAR_GLOBAL"):
            lines.insert(i + 1, shift)
            break
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def test_clean_tree_has_no_persistent_findings(git_workspace):
    data = run_analyze_json(git_workspace, extra=["--rule", "CTS0004"])
    assert data["findings"] == []
    assert data["complete"] is True


def test_reordered_persistent_is_flagged(git_workspace):
    _reorder_persistent(git_workspace)
    data = run_analyze_json(git_workspace, extra=["--rule", "CTS0004"])
    assert len(data["findings"]) == 1
    f = data["findings"][0]
    assert f["rule_id"] == "CTS0004"
    assert f["severity"] == "danger"
    assert f["anchor"] == "p_nShift"
    assert f["location"]["path"] == "POUs/GVL_Persistent.st"


def test_explicit_base_option(git_workspace):
    _reorder_persistent(git_workspace)
    data = run_analyze_json(
        git_workspace, extra=["--rule", "CTS0004", "--base", "HEAD"]
    )
    assert len(data["findings"]) == 1


def test_no_git_emits_diagnostic(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    data = run_analyze_json(root, extra=["--rule", "CTS0004"])
    assert data["complete"] is False
    kinds = [d["kind"] for d in data["diagnostics"]]
    assert "git-base" in kinds
    assert data["_exit"] == 0  # incomplete policy defaults to warn


def test_no_git_with_incomplete_error_exits_3(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    data = run_analyze_json(root, extra=["--rule", "CTS0004", "--incomplete", "error"])
    assert data["_exit"] == 3


def test_new_persistent_file_is_not_a_finding(git_workspace):
    # Add a brand-new PERSISTENT GVL (absent from base): no finding.
    path = os.path.join(git_workspace, "project-view", "POUs", "GVL_New.st")
    open(path, "w", encoding="utf-8").write(
        "VAR_GLOBAL PERSISTENT RETAIN\n    q : INT := 0;\nEND_VAR\n"
    )
    data = run_analyze_json(git_workspace, extra=["--rule", "CTS0004"])
    assert data["findings"] == []


def test_inserting_middle_variable_is_not_an_order_change(git_workspace):
    path = os.path.join(git_workspace, "project-view", "POUs", "GVL_Persistent.st")
    text = open(path, encoding="utf-8").read()
    text = text.replace(
        "    p_bCalibrated : BOOL := FALSE;",
        "    p_bCalibrated : BOOL := FALSE;\n    p_nNewMid : INT := 0;",
    )
    open(path, "w", encoding="utf-8").write(text)
    data = run_analyze_json(git_workspace, extra=["--rule", "CTS0004"])
    assert data["findings"] == []

def test_path_scoped_exclude_stops_git_use_and_findings(git_workspace):
    """A tree-wide rule-scope exclude for CTS0004 fully scopes the rule
    out: it must not request GIT_BASE (no git process, no spurious git
    diagnostic) and must produce no finding, while other rules on the
    same paths keep running.

    The bogus base proves the absence of a git request: had the rule been
    dispatched, resolving the base would have produced a git-base
    diagnostic.
    """
    _reorder_persistent(git_workspace)
    cfg = os.path.join(git_workspace, "cts-analyze.toml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(
            "[analyze]\n"
            'base = "refs/does-not-exist"\n'
            "\n"
            "[[rule_scope]]\n"
            'path = "**"\n'
            'exclude = ["CTS0004"]\n'
        )

    data = run_analyze_json(git_workspace)
    assert not any(f["rule_id"] == "CTS0004" for f in data["findings"])
    assert not any(d.get("rule_id") == "CTS0004" for d in data["diagnostics"])
    assert not any(d["kind"] == "git-base" for d in data["diagnostics"])
    # A second rule for the same path still runs.
    assert any(f["rule_id"] == "CTS0001" for f in data["findings"])
    # No rule was hurt by the scope: the run is complete.
    assert data["complete"] is True


def test_global_enabled_false_skips_history_rule(git_workspace):
    """Global ``enabled = false`` still disables a rule outright (no git
    request, no finding, no diagnostic)."""
    _reorder_persistent(git_workspace)
    cfg = os.path.join(git_workspace, "cts-analyze.toml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write("[rules.CTS0004]\nenabled = false\n")

    data = run_analyze_json(git_workspace)
    assert not any(f["rule_id"] == "CTS0004" for f in data["findings"])
    assert not any(d.get("rule_id") == "CTS0004" for d in data["diagnostics"])
    assert data["complete"] is True

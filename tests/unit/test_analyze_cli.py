"""
test_analyze_cli.py - CLI surface: formats, subcommands, deterministic JSON
and SARIF snapshots.
"""

import json
import os

from analyze_helpers import copy_fixture, fixture_project_view, run_cli


def test_json_snapshot_is_deterministic():
    code1, out1, _ = run_cli(
        ["analyze", "--workspace", fixture_project_view(), "--format", "json"]
    )
    code2, out2, _ = run_cli(
        ["analyze", "--workspace", fixture_project_view(), "--format", "json"]
    )
    assert code1 == code2 == 1
    assert out1 == out2


def test_explicit_run_alias_executes_analysis():
    code, out, _ = run_cli(
        ["analyze", "run", "--workspace", fixture_project_view(), "--format", "json"]
    )
    assert code == 1
    assert json.loads(out)["schema_version"] == 1


def test_sarif_output():
    code, out, _ = run_cli(
        [
            "analyze",
            "--workspace",
            fixture_project_view(),
            "--format",
            "sarif",
            "--rule",
            "CTS0001",
        ]
    )
    assert code == 1  # CTS0001 is suspicious and meets the default threshold.
    doc = json.loads(out)
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "cts analyze"
    assert run["results"][0]["ruleId"] == "CTS0001"
    assert run["results"][0]["level"] == "warning"


def test_rules_lists_registry():
    code, out, _ = run_cli(["analyze", "rules", "--format", "json"])
    assert code == 0
    rows = json.loads(out)
    ids = {r["id"] for r in rows}
    assert ids == {
        "CTS0001", "CTS0002", "CTS0003", "CTS0004", "CTS0006", "CTS0007", "CTS0008", "CTS0009", "CTS0010", "CTS0011", "CTS0012", "CTS0013", "CTS0014", "CTS0015", "CTS0016", "CTS0017", "CTS0018", "CTS0019", "CTS0020", "CTS0021", "CTS0022", "CTS0023", "CTS0024", "CTS0025", "CTS0026", "CTS0027", "CTS0028", "CTS0029", "CTS0030", "CTS0031", "CTS0032"
    }


def test_explain_renders_doc():
    code, out, _ = run_cli(["analyze", "explain", "CTS0001", "--format", "md"])
    assert code == 0
    assert out.startswith("---")
    assert "## Why it is dangerous" in out


def test_explain_unknown_rule_exits_2():
    code, _out, err = run_cli(["analyze", "explain", "CTS9999", "--format", "md"])
    assert code == 2
    assert "unknown rule" in err


def test_selftest_passes():
    code, out, _ = run_cli(["analyze", "selftest"])
    assert code == 0, out
    assert "0 failed" in out


def test_fail_on_danger_ignores_suspicious():
    code, out, _ = run_cli(
        [
            "analyze",
            "--workspace",
            fixture_project_view(),
            "--format",
            "json",
            "--fail-on",
            "danger",
        ]
    )
    # Fixture has no danger findings; suspicious ones do not fail.
    assert code == 0
    data = json.loads(out)
    assert data["summary"]["total"] == 22


def test_rule_filter_cli():
    code, out, _ = run_cli(
        [
            "analyze",
            "--workspace",
            fixture_project_view(),
            "--format",
            "json",
            "--rule",
            "CTS0001",
        ]
    )
    data = json.loads(out)
    assert {f["rule_id"] for f in data["findings"]} == {"CTS0001"}


def test_machine_rule_cannot_be_requested_from_human_analyzer():
    code, _out, err = run_cli(
        ["analyze", "--workspace", fixture_project_view(), "--rule", "CTS9999"]
    )
    assert code == 2
    assert "unknown human-analysis rule" in err


def test_pretty_shortcut_forces_text():
    code, out, _ = run_cli(
        ["analyze", "--workspace", fixture_project_view(), "--pretty"]
    )
    assert "[CTS0002]" in out  # text renderer


def test_workspace_not_found_exits_2(tmp_path):
    code, _out, err = run_cli(
        ["analyze", "--workspace", str(tmp_path / "nope"), "--format", "json"]
    )
    assert code == 2
    assert "ERROR" in err


def test_broken_config_exits_2(tmp_path):
    root = tmp_path / "sync"
    (root / "project-view").mkdir(parents=True)
    (root / "cts-analyze.toml").write_text("[analyze\nbroken", encoding="utf-8")
    code, _out, err = run_cli(["analyze", "--workspace", str(root), "--format", "json"])
    assert code == 2
    assert "ERROR" in err


def test_package_data_covers_rule_assets():
    """The wheel must ship rule .py + .md + asset folders."""
    import cds_text_sync.analyze as analyze

    analyze_dir = os.path.dirname(analyze.__file__ or "")
    rules_dir = os.path.join(analyze_dir, "rules")
    rule_py = [f for f in os.listdir(rules_dir) if f.endswith(".py") and f != "__init__.py"]
    md = [f for f in os.listdir(rules_dir) if f.endswith(".md")]
    assert len(rule_py) == 31
    assert len(md) == 31
    stems = {f[:-3] for f in rule_py}
    assert stems == {f[:-3] for f in md}


def _write_config(root, text):
    path = os.path.join(root, "cts-analyze.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_severity_override_in_json_and_exit_code(tmp_path):
    """Phase 1 e2e: configured severity appears in JSON findings/summary and
    drives --fail-on; removing the override restores the declared severity."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    _write_config(root, '[rules.CTS0001]\nseverity = "danger"\n')

    code, out, _ = run_cli(
        [
            "analyze",
            "--workspace",
            root,
            "--format",
            "json",
            "--fail-on",
            "danger",
        ]
    )
    assert code == 1
    data = json.loads(out)
    cts0001 = [f for f in data["findings"] if f["rule_id"] == "CTS0001"]
    assert cts0001
    assert all(f["severity"] == "danger" for f in cts0001)
    assert data["summary"]["by_severity"]["danger"] >= len(cts0001)

    # Same process, no override: the declared severity is back.
    os.remove(_write_config(root, ""))
    code, out, _ = run_cli(
        [
            "analyze",
            "--workspace",
            root,
            "--format",
            "json",
            "--fail-on",
            "danger",
        ]
    )
    assert code == 0
    data = json.loads(out)
    assert data["summary"]["by_severity"]["danger"] == 0


def _seed_baseline_with_schema(root, schema):
    state_dir = os.path.join(root, ".cts-analyze")
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "baseline.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"schema_version": 1, "fingerprint_schema": schema, "entries": []},
            fh,
        )


def test_analyze_rejects_incompatible_baseline_schema(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    _seed_baseline_with_schema(root, 2)
    code, _out, err = run_cli(["analyze", "--workspace", root, "--format", "json"])
    assert code == 2
    assert "baseline fingerprint schema 2 is unsupported" in err
    assert "baseline update" in err


def test_baseline_check_rejects_incompatible_schema(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    _seed_baseline_with_schema(root, 2)
    code, _out, err = run_cli(["analyze", "baseline", "check", "--workspace", root])
    assert code == 2
    assert "baseline fingerprint schema 2 is unsupported" in err


def test_triage_apply_rejects_incompatible_schema(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    _seed_baseline_with_schema(root, 2)
    decisions = tmp_path / "decisions.json"
    decisions.write_text("[]", encoding="utf-8")
    code, _out, err = run_cli(
        [
            "analyze",
            "triage",
            "--apply",
            str(decisions),
            "--workspace",
            root,
        ]
    )
    assert code == 2
    assert "baseline fingerprint schema 2 is unsupported" in err


def test_baseline_update_recovers_from_incompatible_schema(tmp_path):
    """The documented recovery command rewrites an old baseline and a
    subsequent normal run succeeds again."""
    root = str(tmp_path / "sync")
    copy_fixture(root)
    _seed_baseline_with_schema(root, 2)

    code, _out, _err = run_cli(["analyze", "baseline", "update", "--workspace", root])
    assert code == 0
    baseline_path = os.path.join(root, ".cts-analyze", "baseline.json")
    data = json.load(open(baseline_path, encoding="utf-8"))
    assert data["fingerprint_schema"] == 1

    code, _out, _err = run_cli(["analyze", "--workspace", root, "--format", "json"])
    assert code != 2  # schema policy satisfied; findings decide the exit code

"""
CLI triage integration tests: decisions, validation, atomic
state writes.
"""

import json
import os

from analyze_helpers import copy_fixture, run_analyze_json, run_cli


def _findings(workspace, rule="CTS0002"):
    data = run_analyze_json(workspace, extra=["--rule", rule])
    return data["findings"]


def test_apply_suppress_round_trip(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    findings = _findings(root)
    target = findings[0]
    decisions = [
        {
            "fingerprint": target["fingerprint"],
            "action": "suppress",
            "reason": "read by HMI symbol config",
            "rule_id": target["rule_id"],
        }
    ]
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(json.dumps(decisions))

    code, out, err = run_cli(
        [
            "analyze",
            "triage",
            "--apply",
            str(decisions_path),
            "--workspace",
            root,
            "--format",
            "json",
        ]
    )
    assert code == 0
    report = json.loads(out)
    assert report["summary"]["suppressed"] == 1

    # The suppression is now active: that finding disappears.
    after = run_analyze_json(root)
    fingerprints = {f["fingerprint"] for f in after["findings"]}
    assert target["fingerprint"] not in fingerprints
    assert after["summary"]["suppressed"] == 1


def test_apply_rejects_unknown_fingerprint(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            [
                {
                    "fingerprint": "cts1:doesnotexist",
                    "action": "suppress",
                    "reason": "ghost",
                }
            ]
        )
    )
    code, _out, err = run_cli(
        ["analyze", "triage", "--apply", str(decisions_path), "--workspace", root]
    )
    assert code == 2
    assert "does not match any finding" in err


def test_apply_baseline_action(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    findings = _findings(root)
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            [
                {
                    "fingerprint": findings[0]["fingerprint"],
                    "action": "baseline",
                }
            ]
        )
    )
    code, _out, _err = run_cli(
        ["analyze", "triage", "--apply", str(decisions_path), "--workspace", root]
    )
    assert code == 0
    baseline_path = os.path.join(root, ".cts-analyze", "baseline.json")
    assert os.path.isfile(baseline_path)
    data = json.load(open(baseline_path, encoding="utf-8"))
    assert len(data["entries"]) == 1


def test_apply_writes_atomically(tmp_path):
    root = str(tmp_path / "sync")
    copy_fixture(root)
    findings = _findings(root)
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            [
                {
                    "fingerprint": f["fingerprint"],
                    "action": "suppress",
                    "reason": f"because {i}",
                }
                for i, f in enumerate(findings)
            ]
        )
    )
    code, _out, _err = run_cli(
        ["analyze", "triage", "--apply", str(decisions_path), "--workspace", root]
    )
    assert code == 0
    state_dir = os.path.join(root, ".cts-analyze")
    leftovers = [f for f in os.listdir(state_dir) if f.endswith(".tmp")]
    assert leftovers == []


"""Contract every rule fixer must satisfy, independent of the rule.

The desktop UI applies fixes without re-analysing between the members of a
group: it captures the findings once and calls ``rule.fix`` for each of them
in turn, reusing the line numbers from that single analysis.  Three
properties make that safe, and none of them was covered before:

* convergence - applying the offered fix actually removes the finding, and
  does not introduce a new one;
* idempotence - applying the same fix again is a no-op, so a double click or
  a stale group member cannot corrupt the source;
* line-count stability - a fixer may only rewrite lines, never add or remove
  them, otherwise every later member of the group is applied to the wrong
  line.

The samples are deliberately hand-written rather than harvested from the rule
docs: the doc snippets are fragments that the selftest wraps in a synthetic
POU, while a fixer receives a whole ``.st`` file.
"""

from __future__ import annotations

import re

import pytest

from cds_static_analyzer.config import ResolvedConfig
from cds_static_analyzer.project import ProjectSnapshot, _build_st_unit
from cds_static_analyzer.registry import load_builtin_rules
from cds_static_analyzer.runner import RunOptions, run_analysis
from cds_static_analyzer.workspace import Workspace


def _run(rule_id, text):
    unit = _build_st_unit("P.st", text)
    result = run_analysis(
        Workspace(root=".", project_view=".", state_dir=".cts-analyze"),
        ProjectSnapshot(".", [unit]),
        ResolvedConfig(),
        RunOptions(rule_filter={rule_id}),
    )
    assert not [d for d in result.diagnostics if d.kind == "rule-error"]
    return result.findings


# One sample per fixable rule.  Each must contain a defect the rule reports
# and its fixer can repair without human judgement.
SAMPLES = {
    "CTS0007": (
        "PROGRAM P\nVAR\n    total : INT;\nEND_VAR\nIMPLEMENTATION\n"
        "IF ready THEN\n"
        "\tFOR i := 1 TO 10 DO\n"
        "\t\tvalue := i;\n"
        "\t\t\ttotal := total + value;\n"
        "\tEND_FOR\n"
        "END_IF;\n"
    ),
    "CTS0008": (
        "PROGRAM P\nVAR\n"
        "    short_name : INT;\n"
        "    much_longer_name: BOOL;\n"
        "    other : BYTE;\n"
        "END_VAR\nIMPLEMENTATION\nEND_PROGRAM\n"
    ),
}


def _fixable_rule_ids():
    return sorted(
        rule_id for rule_id, rule in load_builtin_rules().items() if rule.fix
    )


def test_every_fixable_rule_has_a_contract_sample():
    """A new fixer must arrive with a sample, or this suite silently skips it."""
    assert set(_fixable_rule_ids()) == set(SAMPLES)


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
def test_autofix_converges(rule_id):
    text = SAMPLES[rule_id]
    rule = load_builtin_rules()[rule_id]
    findings = _run(rule_id, text)
    assert findings, f"{rule_id} sample no longer reports anything"

    fixed = text
    for finding in findings:
        fixed = rule.fix(fixed, finding.to_dict())
    assert fixed != text

    assert not _run(rule_id, fixed), (
        f"{rule_id} still reports findings after applying its own fix"
    )


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
def test_autofix_preserves_the_line_count(rule_id):
    """Group apply reuses analysis-time line numbers for every member."""
    text = SAMPLES[rule_id]
    rule = load_builtin_rules()[rule_id]
    for finding in _run(rule_id, text):
        fixed = rule.fix(text, finding.to_dict())
        assert fixed.count("\n") == text.count("\n")
        assert len(fixed.split("\n")) == len(text.split("\n"))


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
def test_autofix_is_idempotent(rule_id):
    text = SAMPLES[rule_id]
    rule = load_builtin_rules()[rule_id]
    findings = [finding.to_dict() for finding in _run(rule_id, text)]

    fixed = text
    for finding in findings:
        fixed = rule.fix(fixed, finding)
    for finding in findings:
        assert rule.fix(fixed, finding) == fixed, (
            f"{rule_id} fixer keeps rewriting an already repaired source"
        )


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
def test_autofix_only_redistributes_whitespace(rule_id):
    """No fixer today may alter code, only the whitespace around it.

    Both current fixers are formatters (indentation, declaration alignment).
    A future fixer that rewrites real code must relax this test deliberately,
    with the UI's blind group apply in mind.
    """
    text = SAMPLES[rule_id]
    rule = load_builtin_rules()[rule_id]
    squeeze = lambda line: re.sub(r"\s+", "", line)  # noqa: E731
    for finding in _run(rule_id, text):
        fixed = rule.fix(text, finding.to_dict())
        before = [squeeze(line) for line in text.split("\n")]
        after = [squeeze(line) for line in fixed.split("\n")]
        assert before == after


@pytest.mark.parametrize("rule_id", sorted(SAMPLES))
def test_autofix_ignores_a_finding_it_cannot_place(rule_id):
    """A fixer must degrade to a no-op, never crash the bridge."""
    rule = load_builtin_rules()[rule_id]
    text = SAMPLES[rule_id]
    assert rule.fix(text, {}) == text
    assert rule.fix(text, {"location": {}}) == text

"""
test_analyze_registry.py - Registry loading, doc completeness, and the
engine/analyze import boundary.
"""

import os

from cds_text_sync.analyze.registry import (
    RULE_SUFFIX,
    RegistryError,
    load_builtin_rules,
)


def cds_text_sync_analyze_path():
    import cds_text_sync.analyze as analyze

    return os.path.dirname(analyze.__file__ or "")


def test_all_human_builtin_rules_load():
    rules = load_builtin_rules()
    assert set(rules) == {
        "CTS0001", "CTS0002", "CTS0003", "CTS0004", "CTS0006", "CTS0007", "CTS0008", "CTS0009", "CTS0010", "CTS0011", "CTS0012", "CTS0013", "CTS0014", "CTS0015", "CTS0016", "CTS0017", "CTS0018", "CTS0019", "CTS0020", "CTS0021", "CTS0022", "CTS0023", "CTS0024", "CTS0025", "CTS0026", "CTS0027", "CTS0028", "CTS0029", "CTS0030", "CTS0031", "CTS0032", "CTS0033", "CTS0034", "CTS0035", "CTS0036", "CTS0037", "CTS0038", "CTS0039", "CTS0040", "CTS0041", "CTS0042", "CTS0043"
    }


def test_rule_metadata_is_valid():
    rules = load_builtin_rules()
    for rule in rules.values():
        assert rule.id.startswith("CTS") and len(rule.id) == 7
        assert rule.title
        assert rule.severity in ("danger", "suspicious", "style")
        assert rule.scope.value in ("unit", "project", "history")
        assert rule.kinds
        assert rule.requires


def test_every_rule_has_a_doc_with_mandatory_sections():
    rules = load_builtin_rules()
    mandatory = (
        "## What it is",
        "## Why it is dangerous",
        "## Example",
        "## When ignoring is legitimate",
        "## How to fix",
    )
    for rule in rules.values():
        with open(rule.doc_path, encoding="utf-8") as fh:
            doc = fh.read()
        for section in mandatory:
            assert section in doc, f"{rule.id}: missing {section}"
        assert doc.startswith("---\n"), f"{rule.id}: missing front matter"
        # Every doc carries executable good/bad examples.
        assert "```st good" in doc and "```st bad" in doc


def test_front_matter_has_no_behavior_metadata():
    """Behavior metadata (severity, kinds, tier) lives only in rule .py files.

    The docs' ``applies to`` line is generated from rule.kinds (see
    ``cts analyze explain``); a hand-written copy would drift.
    Also ensure no front matter carries tags: or restates severity/topic values.
    """
    from cds_text_sync.analyze.rules_api import ALLOWED_TOPICS

    rules = load_builtin_rules()
    forbidden = ("applies_to", "severity", "tier", "scope", "requires", "tags")
    severity_values = {"danger", "suspicious", "style"}
    topic_values = ALLOWED_TOPICS

    for rule in rules.values():
        with open(rule.doc_path, encoding="utf-8") as fh:
            doc = fh.read()
        # front is the YAML between the leading '---\n' and the closing one
        parts = doc.split("---\n", 2)
        front = parts[1] if len(parts) >= 3 else ""
        for token in forbidden:
            assert token not in front, (
                f"{rule.id}: {token} must not appear in front matter"
            )
        # Also check that severity values and topic values don't appear in front
        for sev_value in severity_values:
            assert sev_value not in front, (
                f"{rule.id}: severity value {sev_value!r} must not appear in front matter"
            )
        for topic_value in topic_values:
            assert topic_value not in front, (
                f"{rule.id}: topic value {topic_value!r} must not appear in front matter"
            )


def test_stem_matches_rule_id():
    rules = load_builtin_rules()
    for rule in rules.values():
        assert os.path.basename(rule.source_path).startswith(rule.id + "_")


def test_rule_files_use_py_suffix():
    rules = load_builtin_rules()
    for rule in rules.values():
        assert rule.source_path.endswith(RULE_SUFFIX)


def test_engine_does_not_import_analyze():
    """The dependency arrow is analyze -> engine, never the reverse."""
    import ast

    engine_dir = os.path.join(os.path.dirname(cds_text_sync_analyze_path()), "engine")
    offenders = []
    for filename in os.listdir(engine_dir):
        if not filename.endswith(".py"):
            continue
        path = os.path.join(engine_dir, filename)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(
                        "cds_text_sync.analyze"
                    ) or alias.name.startswith("analyze"):
                        offenders.append((filename, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(
                    "cds_text_sync.analyze"
                ) or node.module.startswith("analyze"):
                    offenders.append((filename, node.module))
    assert offenders == [], f"engine must not import analyze: {offenders}"


def test_rule_asset_budget():
    """Rule assets stay text/SVG and light (imp_plan.md budget).

    In-repo assets are text and SVG only; GIFs are allowed only by URL with
    a cache. Total asset weight must stay well under ~2 MB so the one-command
    installer does not bloat.
    """
    allowed_extensions = {".svg", ".txt", ".html", ".css"}
    rules_root = os.path.join(cds_text_sync_analyze_path(), "rules")
    total = 0
    for dirpath, dirnames, filenames in os.walk(rules_root):
        dirnames[:] = [
            d for d in dirnames if d != "__pycache__" and not d.startswith(".")
        ]
        for filename in filenames:
            if filename.endswith((".md", ".py", ".pyc")):
                continue  # code and docs are not "assets"
            ext = os.path.splitext(filename)[1].lower()
            assert ext in allowed_extensions, (
                f"forbidden asset type {ext!r} in {os.path.join(dirpath, filename)}"
            )
            total += os.path.getsize(os.path.join(dirpath, filename))
    assert total <= 2_000_000, f"rule assets exceed budget: {total} bytes"


def test_one_file_per_rule():
    """``rules/`` holds exactly one ``.py`` and one ``.md`` per rule.

    No extra modules and no sub-packages: a rule that is split across a
    manifest and an implementation module duplicates its id, and the split
    has bitten us before (a merge that pasted a stale implementation body
    back into the manifest went unnoticed because the two could disagree).
    """
    rules_root = os.path.join(cds_text_sync_analyze_path(), "rules")
    entries = [e for e in sorted(os.listdir(rules_root)) if e != "__pycache__"]
    stray = [e for e in entries if not e.endswith((".py", ".md"))]
    assert stray == [], f"rules/ must hold only .py and .md files: {stray}"

    rules = load_builtin_rules()
    assert len(entries) == 2 * len(rules) + 1, (
        f"expected one .py + one .md per rule ({len(rules)} rules) plus catalog, "
        f"got {len(entries)} files"
    )


def test_rules_do_not_declare_identity():
    """Rule identity lives in the registry and ``_collect``, not in the rule.

    The runner stamps id/title/severity onto every finding from the
    registry Rule; a rule restating any of it in its ``check`` is how the
    four-way duplication creeps back. The ``RULE = RuleSpec(...)`` manifest
    at the bottom of each file is the one place identity is written.
    """
    rules = load_builtin_rules()
    forbidden = ("RULE_ID", "SEVERITY", "rule_title=")
    for rule in rules.values():
        with open(rule.source_path, encoding="utf-8") as fh:
            text = fh.read()
        # The manifest itself legitimately names id/title/severity.
        body = text.split("RULE = RuleSpec(")[0]
        for token in forbidden:
            assert token not in body, (
                f"{os.path.basename(rule.source_path)} must not declare "
                f"identity ({token}); the runner stamps it from the registry"
            )


def test_runner_stamps_registry_identity():
    """The runner stamps registry identity onto every finding.

    rule_id/title/severity on a finding come from the registry Rule, so
    editing a rule ``.py`` manifest reaches the findings and the two
    cannot drift.
    """
    from cds_text_sync.analyze.config import ResolvedConfig
    from cds_text_sync.analyze.project import build_snapshot
    from cds_text_sync.analyze.runner import RunOptions, run_analysis
    from cds_text_sync.analyze.workspace import WorkspaceResolver

    from analyze_helpers import fixture_project_view

    registry = load_builtin_rules()
    workspace = WorkspaceResolver(workspace=fixture_project_view()).resolve()
    snapshot = build_snapshot(workspace.project_view)
    result = run_analysis(
        workspace,
        snapshot,
        ResolvedConfig(),
        RunOptions(rule_filter={"CTS0001"}),
    )
    assert result.findings
    for finding in result.findings:
        rule = registry[finding.rule_id]
        assert finding.rule_title == rule.title
        assert finding.severity == rule.severity


def test_registry_duplicate_stem_is_fatal(tmp_path, monkeypatch):
    import cds_text_sync.analyze.registry as registry

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "CTS0001_a.py").write_text(
        "from cds_text_sync.analyze.rules_api import RuleSpec\n"
        "RULE = RuleSpec(id='CTS0001', title='x', severity='style', "
        "scope='unit', requires=[], kinds='ANY', summary='s', check=check)\n"
        "def check(unit, ctx): return []\n",
        encoding="utf-8",
    )
    (rules_dir / "CTS0001_a.md").write_text("doc\n", encoding="utf-8")
    monkeypatch.setattr(registry, "rules_dir", lambda: str(rules_dir))
    with pytest.raises(RegistryError):
        load_builtin_rules()


def test_retired_rule_id_cannot_be_reintroduced(monkeypatch):
    """A retired id is fatal on load: fingerprints, baselines and user
    suppressions in the field are keyed by rule id, so recycling one would
    silently re-target them."""
    import cds_text_sync.analyze.registry as registry

    registry.clear_registry_cache()  # clear the cached rules
    monkeypatch.setattr(registry, "_RETIRED_IDS", frozenset({"CTS0001"}))
    with pytest.raises(RegistryError, match="retired"):
        load_builtin_rules()
    registry.clear_registry_cache()  # restore for other tests


def test_topic_is_from_the_allowed_set():
    """All rules must declare a topic from the allowed set.

    Topics are read from the registry and used for grouping in the UI.
    """
    from cds_text_sync.analyze.rules_api import ALLOWED_TOPICS

    rules = load_builtin_rules()
    for rule in rules.values():
        assert rule.topic in ALLOWED_TOPICS, (
            f"{rule.id}: topic {rule.topic!r} not in allowed set: "
            f"{', '.join(sorted(ALLOWED_TOPICS))}"
        )


def test_rulespec_validate_rejects_bad_topic():
    """RuleSpec.validate rejects topics not in the allowed set."""
    from cds_text_sync.analyze.rules_api import RuleSpec, RuleSpecError, ALLOWED_TOPICS
    from cds_text_sync.analyze.capabilities import Scope, Capability

    def dummy_check(unit, ctx):
        pass

    # Bad topic
    with pytest.raises(RuleSpecError, match="not in allowed set"):
        RuleSpec(
            id="CTS9999",
            title="test",
            severity="style",
            scope=Scope.UNIT,
            requires={Capability.ST_TEXT},
            kinds="CALLABLE",
            summary="test",
            check=dummy_check,
            topic="BadTopic",
        ).validate()

    # Valid topic
    spec = RuleSpec(
        id="CTS9999",
        title="test",
        severity="style",
        scope=Scope.UNIT,
        requires={Capability.ST_TEXT},
        kinds="CALLABLE",
        summary="test",
        check=dummy_check,
        topic="Code quality",
    )
    spec.validate()  # should not raise
    assert spec.topic == "Code quality"


def test_rulespec_options_validate_type_and_names():
    """RuleSpec.validate rejects invalid option defaults and reserved names."""
    from cds_text_sync.analyze.rules_api import RuleSpec, RuleSpecError
    from cds_text_sync.analyze.capabilities import Scope, Capability

    def dummy_check(unit, ctx):
        pass

    # Bad default type (list is not allowed)
    with pytest.raises(RuleSpecError, match="list"):
        RuleSpec(
            id="CTS9999",
            title="test",
            severity="style",
            scope=Scope.UNIT,
            requires={Capability.ST_TEXT},
            kinds="CALLABLE",
            summary="test",
            check=dummy_check,
            topic="Code quality",
            options={"my_list": [1, 2]},  # not allowed
        ).validate()

    # Reserved option name
    with pytest.raises(RuleSpecError, match="reserved"):
        RuleSpec(
            id="CTS9999",
            title="test",
            severity="style",
            scope=Scope.UNIT,
            requires={Capability.ST_TEXT},
            kinds="CALLABLE",
            summary="test",
            check=dummy_check,
            topic="Code quality",
            options={"enabled": 42},  # reserved name
        ).validate()

    # Invalid identifier
    with pytest.raises(RuleSpecError, match="identifier"):
        RuleSpec(
            id="CTS9999",
            title="test",
            severity="style",
            scope=Scope.UNIT,
            requires={Capability.ST_TEXT},
            kinds="CALLABLE",
            summary="test",
            check=dummy_check,
            topic="Code quality",
            options={"bad-name": 42},  # hyphen not allowed
        ).validate()

    # Valid options pass
    spec = RuleSpec(
        id="CTS9999",
        title="test",
        severity="style",
        scope=Scope.UNIT,
        requires={Capability.ST_TEXT},
        kinds="CALLABLE",
        summary="test",
        check=dummy_check,
        topic="Code quality",
        options={"min_count": 4, "ratio": 0.5, "name": "foo"},
    )
    spec.validate()  # should not raise
    assert spec.options == {"min_count": 4, "ratio": 0.5, "name": "foo"}


def test_all_bad_blocks_have_counts_and_markers():
    """Item 5: selftest expectations. All bad blocks must have explicit counts
    and at least one // cts:here marker to lock in finding line assertions."""
    import re

    rules = load_builtin_rules()
    bad_block_pattern = re.compile(r"```st\s+bad(\s+\d+)?\s*\n(.*?)```", re.DOTALL)
    marker_pattern = re.compile(r"//\s*cts:here")

    for rule in rules.values():
        with open(rule.doc_path, encoding="utf-8") as fh:
            doc = fh.read()

        for match in bad_block_pattern.finditer(doc):
            count_str = match.group(1)
            block_text = match.group(2)

            # Check explicit count
            assert count_str is not None and count_str.strip(), (
                f"{rule.id}: bad block must have explicit count (e.g. 'bad 2'). "
                f"Block: {block_text[:50]}"
            )

            # Check at least one // cts:here marker
            assert marker_pattern.search(block_text), (
                f"{rule.id}: bad block must have at least one '// cts:here' marker. "
                f"Block: {block_text[:50]}"
            )


import pytest  # noqa: E402  (used above; kept at bottom for lint sanity)

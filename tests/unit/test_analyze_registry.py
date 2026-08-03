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
        "CTS0001", "CTS0002", "CTS0003", "CTS0004", "CTS0006", "CTS0007", "CTS0008", "CTS0009", "CTS0010"
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
    """Behavior metadata (severity, kinds, tier) lives only in .ctsrule.

    The docs' ``applies to`` line is generated from rule.kinds (see
    ``cts analyze explain``); a hand-written copy would drift.
    """
    rules = load_builtin_rules()
    forbidden = ("applies_to", "severity", "tier", "scope", "requires")
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


def test_stem_matches_rule_id():
    rules = load_builtin_rules()
    for rule in rules.values():
        assert os.path.basename(rule.source_path).startswith(rule.id + "_")


def test_rule_files_use_ctsrule_suffix():
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
            if filename.endswith((".ctsrule", ".md", ".py", ".pyc")):
                continue  # code and docs are not "assets"
            ext = os.path.splitext(filename)[1].lower()
            assert ext in allowed_extensions, (
                f"forbidden asset type {ext!r} in {os.path.join(dirpath, filename)}"
            )
            total += os.path.getsize(os.path.join(dirpath, filename))
    assert total <= 2_000_000, f"rule assets exceed budget: {total} bytes"


def test_registry_duplicate_stem_is_fatal(tmp_path, monkeypatch):
    import cds_text_sync.analyze.registry as registry

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "CTS0001_a.ctsrule").write_text(
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


import pytest  # noqa: E402  (used above; kept at bottom for lint sanity)

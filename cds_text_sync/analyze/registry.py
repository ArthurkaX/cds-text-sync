"""
registry.py - Loading and validating the built-in rules.

Rules live in ``cds_text_sync/analyze/rules/*.ctsrule``. The suffix exists so
the CODESYS ScriptDir scanner (which shows every ``.py`` in its menu) never
picks the rules up; the loader is an explicit ``SourceFileLoader`` because the
suffix is unknown to the import machinery.

Registry invariants (fatal on violation - a broken registry is a broken tool):

* one stem == exactly one ``RULE``;
* one rule id == exactly one file and exactly one Markdown document;
* metadata (id, severity, scope, kinds, capabilities) validates;
* duplicate ids / broken metadata / import errors abort the run.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
import sys

from cds_text_sync.analyze.rules_api import RuleSpec, RuleSpecError
from cds_text_sync.analyze.st.kinds import expand_kinds

RULE_SUFFIX = ".ctsrule"
_RULE_ID_RE = re.compile(r"^CTS\d{4}$")
_REGISTRY_CACHE = {}
_RULE_ID_ASSIGNMENTS = {
    "CTS0001": "CTS0001_commented_code",
    "CTS0002": "CTS0002_unused_input",
    "CTS0003": "CTS0003_case_without_else",
    "CTS0004": "CTS0004_magic_number",
    "CTS0006": "CTS0006_array_bounds",
    "CTS0007": "CTS0007_indentation",
    "CTS0008": "CTS0008_variable_alignment",
    "CTS0009": "CTS0009_output_not_assigned",
    "CTS0010": "CTS0010_redundant_boolean_if",
    "CTS0011": "CTS0011_assigned_not_read",
    "CTS0012": "CTS0012_overwrite_without_read",
    "CTS0013": "CTS0013_dead_symbol",
}


class RegistryError(Exception):
    """The built-in rule registry is broken; analysis cannot start."""


class Rule:
    """A loaded, validated rule ready for dispatch."""

    def __init__(self, spec, stem, source_path, doc_path):
        self.id = spec.id
        self.title = spec.title
        self.severity = spec.severity
        self.scope = spec.scope
        self.requires = spec.requires
        self.kinds = expand_kinds(spec.kinds)
        self.summary = spec.summary
        self.topic = spec.topic
        self.check = spec.check
        self.stem = stem
        self.source_path = source_path
        self.doc_path = doc_path

    def __repr__(self):
        return f"<Rule {self.id} {self.title} scope={self.scope.value}>"

    def applicable_to(self, kind):
        return kind in self.kinds


def rules_dir():
    return os.path.join(os.path.dirname(__file__), "rules")


def _load_module(path):
    name = "cts_rule_" + os.path.splitext(os.path.basename(path))[0]
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, str(path), loader=loader)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RegistryError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # normal tracebacks
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RegistryError(f"rule {path} failed to import: {exc}") from exc
    return module


def load_builtin_rules():
    """Load every built-in rule. Returns a dict {rule_id: Rule}."""
    root = rules_dir()
    cache_key = os.path.abspath(root)
    cached = _REGISTRY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    rules = {}
    stems = set()
    for filename in sorted(os.listdir(root)):
        if not filename.endswith(RULE_SUFFIX):
            continue
        stem = filename[: -len(RULE_SUFFIX)]
        if stem in stems:
            raise RegistryError(f"duplicate rule stem: {stem}")
        stems.add(stem)

        path = os.path.join(root, filename)
        module = _load_module(path)
        spec = getattr(module, "RULE", None)
        if spec is None or not isinstance(spec, RuleSpec):
            raise RegistryError(f"{filename}: module must define RULE = RuleSpec(...)")
        try:
            spec.validate()
        except RuleSpecError as exc:
            raise RegistryError(f"{filename}: {exc}") from exc

        rule_id = spec.id
        if not _RULE_ID_RE.match(rule_id):
            raise RegistryError(
                f"{filename}: rule id {rule_id!r} must match CTS\\d{{4}}"
            )
        if not stem.startswith(rule_id + "_"):
            raise RegistryError(
                f"{filename}: stem must start with the rule id ({rule_id})"
            )
        assigned_stem = _RULE_ID_ASSIGNMENTS.get(rule_id)
        if assigned_stem is not None and stem != assigned_stem:
            raise RegistryError(
                f"{filename}: rule id {rule_id} is already assigned to "
                f"{assigned_stem}; IDs must not be recycled"
            )
        if rule_id in rules:
            raise RegistryError(f"duplicate rule id: {rule_id}")

        doc_path = os.path.join(root, stem + ".md")
        if not os.path.isfile(doc_path):
            raise RegistryError(
                f"{filename}: missing documentation {stem}.md (every rule needs one)"
            )

        rules[rule_id] = Rule(spec, stem, path, doc_path)

    if not rules:
        raise RegistryError("no rules found in the built-in rules directory")
    _REGISTRY_CACHE[cache_key] = rules
    return rules


def clear_registry_cache():
    """Clear the process-local registry cache (primarily for tests/tools)."""
    _REGISTRY_CACHE.clear()


def doc_asset_paths(rule):
    """Asset paths for a rule's documentation (its stem folder)."""
    folder = os.path.join(rules_dir(), rule.stem)
    if not os.path.isdir(folder):
        return []
    out = []
    for dirpath, _dirnames, filenames in os.walk(folder):
        for filename in sorted(filenames):
            out.append(os.path.join(dirpath, filename))
    return out

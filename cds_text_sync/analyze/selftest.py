"""Rule selftest runner using the same context contract as production."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from cds_text_sync.analyze import project as project_mod
from cds_text_sync.analyze.capabilities import Scope
from cds_text_sync.analyze.config import ResolvedConfig
from cds_text_sync.analyze.model import Finding
from cds_text_sync.analyze.registry import RegistryError, load_builtin_rules
from cds_text_sync.analyze.runner import AnalysisContext
from cds_text_sync.analyze.workspace import Workspace


def extract_st_blocks(doc):
    pattern = re.compile(r"```st\s+(good|bad)\s*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(doc):
        yield match.group(1), match.group(2).strip("\n")


def run(out):
    try:
        registry = load_builtin_rules()
    except RegistryError as exc:
        out.write(f"selftest: {exc}\n")
        return 2
    failures = []
    passed = 0
    for rule_id in sorted(registry):
        rule = registry[rule_id]
        with open(rule.doc_path, encoding="utf-8") as fh:
            doc = fh.read()
        blocks = list(extract_st_blocks(doc))
        if not blocks:
            failures.append(f"{rule_id}: no ```st good/bad examples in doc")
            continue
        good_text = next((text for tag, text in blocks if tag == "good"), "")
        for tag, text in blocks:
            try:
                actual = run_snippet(
                    rule, text, base_text=good_text if rule.scope == Scope.HISTORY else None
                )
            except Exception as exc:
                failures.append(f"{rule_id} ({tag}): crashed: {exc}")
                continue
            expect = tag == "bad"
            if expect and not actual:
                failures.append(f"{rule_id} ({tag}): expected a finding, got none")
            elif not expect and actual:
                failures.append(
                    f"{rule_id} ({tag}): expected clean, got {len(actual)} finding(s)"
                )
            else:
                passed += 1
    out.write(f"selftest: {passed} blocks passed, {len(failures)} failed\n")
    for failure in failures:
        out.write(f"  FAIL {failure}\n")
    return 1 if failures else 0


def run_snippet(rule, text, base_text=None):
    lower = text.lower()
    if "<single" in lower or "<?xml" in lower or "<visual" in lower:
        try:
            unit = project_mod._build_xml_unit("snippet.xml", text)
        except ET.ParseError:
            unit = None
        if unit is None:
            try:
                unit = project_mod._build_xml_unit(
                    "snippet.xml", f"<Visualization>\n{text}\n</Visualization>"
                )
            except ET.ParseError:
                unit = None
    else:
        unit = project_mod._build_st_unit("snippet.st", text)
        if unit is None:
            unit = project_mod._build_st_unit(
                "snippet.st", "PROGRAM Snippet\nVAR\nEND_VAR\n\nIMPLEMENTATION\n\n" + text
            )
    if unit is None:
        raise ValueError("cannot classify snippet as ST or XML")
    snapshot = project_mod.ProjectSnapshot(".", [unit])
    workspace = Workspace(root=".", project_view=".", state_dir=".cts-analyze")
    ctx = _SnippetContext(workspace, snapshot, ResolvedConfig())
    ctx.base_text = base_text
    found = rule.check(unit, ctx) if rule.scope == Scope.UNIT else rule.check(ctx)
    return [item for item in (found or []) if isinstance(item, Finding)]


class _SnippetContext(AnalysisContext):
    def __init__(self, workspace, snapshot, config):
        super().__init__(workspace, snapshot, config, base="HEAD")
        self.base_text = None

    def capability(self, cap):
        from cds_text_sync.analyze.capabilities import Capability
        if cap == Capability.GIT_BASE:
            return _StubGit(self.base_text)
        return super().capability(cap)


class _StubGit:
    def __init__(self, base_text):
        self.base_text = base_text

    def read(self, relpath):
        return self.base_text

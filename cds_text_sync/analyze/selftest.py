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
from cds_text_sync.analyze.st import kinds as K
from cds_text_sync.analyze.workspace import Workspace


def extract_st_blocks(doc):
    # Fence grammar: ```st good|bad [count]
    # bad: at least one (if no count) or exactly count findings
    # good: zero findings (count not allowed)
    pattern = re.compile(r"```st\s+(good|bad)(?:\s+(\d+))?\s*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(doc):
        tag, count_str, text = match.group(1), match.group(2), match.group(3)
        count = int(count_str) if count_str else None
        text = text.strip("\n")
        yield tag, count, text


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
        for tag, expect_count, text in blocks:
            # Validate fence grammar: count on good is an error
            if tag == "good" and expect_count is not None:
                failures.append(f"{rule_id} ({tag}): count not allowed on good blocks")
                continue

            # Strip // cts:here markers with spaces to preserve columns
            text, marker_lines = _strip_markers(text)

            try:
                actual = run_snippet(rule, text)
            except Exception as exc:
                failures.append(f"{rule_id} ({tag}): crashed: {exc}")
                continue

            # Check count
            actual_count = len(actual)
            if tag == "bad":
                if expect_count is None:
                    # No count specified: at least 1
                    if not actual:
                        failures.append(
                            f"{rule_id} ({tag}): expected >= 1 finding, got {actual_count}"
                        )
                        continue
                else:
                    # Count specified: must match exactly
                    if actual_count != expect_count:
                        failures.append(
                            f"{rule_id} ({tag}): expected {expect_count} finding(s), "
                            f"got {actual_count}"
                        )
                        continue

                # Check line anchoring if markers present
                if marker_lines:
                    actual_lines = {f.location.line for f in actual if f.location}
                    if actual_lines != marker_lines:
                        failures.append(
                            f"{rule_id} ({tag}): expected findings on lines {sorted(marker_lines)}, "
                            f"got {sorted(actual_lines)}"
                        )
                        continue
            else:  # tag == "good"
                if actual:
                    failures.append(
                        f"{rule_id} ({tag}): expected clean, got {actual_count} finding(s)"
                    )
                    continue

            passed += 1
    out.write(f"selftest: {passed} blocks passed, {len(failures)} failed\n")
    for failure in failures:
        out.write(f"  FAIL {failure}\n")
    return 1 if failures else 0


def _strip_markers(text):
    """Strip // cts:here markers with spaces, preserving column offsets.

    Returns (stripped_text, marker_lines_set).
    Marker lines are 1-based line numbers.
    """
    lines = text.split("\n")
    marker_lines = set()
    marker_pattern = re.compile(r"//\s*cts:here")

    for i, line in enumerate(lines, 1):
        if marker_pattern.search(line):
            marker_lines.add(i)
            # Replace marker with spaces (same number of chars) to preserve columns
            lines[i - 1] = marker_pattern.sub(
                lambda m: " " * len(m.group(0)), line
            )

    return "\n".join(lines), marker_lines


def run_snippet(rule, text):
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
    units = [unit]
    if rule.scope.value == "project":
        gvl_pattern = re.compile(r"//\s*cts:gvl\s+([^:]+):\s*([^\s]+)", re.IGNORECASE)
        for index, match in enumerate(gvl_pattern.finditer(text), 1):
            gvl, member = match.group(1).strip(), match.group(2).strip()
            units.append(
                project_mod._build_st_unit(
                    f"{gvl}.st",
                    f"VAR_GLOBAL\n    {member} : INT;\nEND_VAR\n",
                )
            )
        task_pattern = re.compile(r"//\s*cts:task\s+([^:]+):\s*([^\s]+)", re.IGNORECASE)
        for index, match in enumerate(task_pattern.finditer(text), 1):
            task = match.group(1).strip()
            # The one ST snippet is stored under ``snippet``; the second
            # token documents the intended POU name but production paths are
            # not available to the selftest harness.
            pou = unit.qualified_name
            xml = (
                '<Single><List Name="PouList"><Single>'
                f'<Single Name="Name">{pou}</Single>'
                "</Single></List></Single>"
            )
            units.append(
                project_mod.Unit(
                    f"task{index}.xml#{task}",
                    K.TASK_CONFIG,
                    task,
                    f"task{index}.xml",
                    xml,
                )
            )
    snapshot = project_mod.ProjectSnapshot(".", units)
    workspace = Workspace(root=".", project_view=".", state_dir=".cts-analyze")
    ctx = AnalysisContext(workspace, snapshot, ResolvedConfig())
    ctx.active_rule = rule
    found = rule.check(unit, ctx) if rule.scope == Scope.UNIT else rule.check(ctx)
    return [item for item in (found or []) if isinstance(item, Finding)]

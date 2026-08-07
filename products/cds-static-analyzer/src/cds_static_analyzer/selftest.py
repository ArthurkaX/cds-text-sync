"""Rule selftest runner using the same context contract as production."""

from __future__ import annotations

import re
from cds_static_analyzer import project as project_mod
from cds_static_analyzer.capabilities import Scope
from cds_static_analyzer.config import ResolvedConfig
from cds_static_analyzer.model import Finding
from cds_static_analyzer.registry import RegistryError, load_builtin_rules
from cds_static_analyzer.runner import AnalysisContext
from cds_static_analyzer.st import kinds as K
from cds_static_analyzer.workspace import Workspace


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
    units = []
    line_adjustments = {}
    for index, (start, segment) in enumerate(_split_snippet_units(text)):
        header = re.search(
            r"(?m)^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION|METHOD|INTERFACE)\s+"
            r"([A-Za-z_]\w*)\b",
            segment,
            re.IGNORECASE,
        )
        stem = header.group(1) if header else f"snippet{index}"
        path = f"{stem}{index if index and stem == 'snippet' else ''}.st"
        unit = project_mod._build_st_unit(path, segment)
        synthetic_prefix_lines = 0
        if unit is None or unit.kind == K.UNKNOWN:
            significant = re.sub(r"(?m)^\s*//.*$", "", segment).lstrip()
            if re.match(r"VAR(?:_[A-Z_]+)?\b", significant, re.IGNORECASE):
                prefix = "PROGRAM Snippet\n"
            else:
                prefix = "PROGRAM Snippet\nVAR\nEND_VAR\nIMPLEMENTATION\n"
            unit = project_mod._build_st_unit(path, prefix + segment)
            synthetic_prefix_lines = prefix.count("\n")
        if unit is None:
            raise ValueError("cannot classify snippet as ST")
        units.append(unit)
        line_adjustments[unit.id] = (
            text[:start].count("\n"), synthetic_prefix_lines
        )

    if not units:
        raise ValueError("cannot classify snippet as ST")
    unit = next(
        (
            candidate
            for candidate, (_start, segment) in zip(
                units, _split_snippet_units(text)
            )
            if "cts:here" in segment
        ),
        next((candidate for candidate in units if candidate.kind in K.CALLABLE), units[0]),
    )
    owner_pattern = re.search(r"//\s*cts:owner\s+([^\s]+)", text, re.IGNORECASE)
    if owner_pattern and unit.kind == K.METHOD:
        old_id = unit.id
        owner = owner_pattern.group(1).strip()
        unit.owner_name = owner
        unit.qualified_name = f"{owner}.{unit.qualified_name.rsplit('.', 1)[-1]}"
        unit.id = project_mod.unit_id(unit.source_path, unit.qualified_name)
        line_adjustments[unit.id] = line_adjustments.pop(old_id)

    fb_pattern = re.compile(
        r"//\s*cts:fb\s+([^\s]+)(?:\s+extends\s+([^\s]+))?",
        re.IGNORECASE,
    )
    for match in fb_pattern.finditer(text):
        name = match.group(1).strip()
        base = match.group(2)
        extends = f" EXTENDS {base}" if base else ""
        units.append(
            project_mod._build_st_unit(
                f"{name}.st",
                f"FUNCTION_BLOCK {name}{extends}\nVAR\nEND_VAR\n",
            )
        )

    method_pattern = re.compile(
        r"//\s*cts:method\s+([^:]+):\s*([^\s]+)", re.IGNORECASE
    )
    for match in method_pattern.finditer(text):
        owner = match.group(1).strip()
        name = match.group(2).strip()
        units.append(
            project_mod._build_st_unit(
                f"{owner}.{name}.st",
                f"METHOD {name}\nIMPLEMENTATION\nEND_METHOD\n",
            )
        )

    interface_pattern = re.compile(r"//\s*cts:interface\s+([^\s]+)", re.IGNORECASE)
    for match in interface_pattern.finditer(text):
        name = match.group(1).strip()
        units.append(
            project_mod._build_st_unit(
                f"{name}.st", f"INTERFACE {name}\nEND_INTERFACE\n"
            )
        )
    function_pattern = re.compile(r"//\s*cts:function\s+([^\s]+)", re.IGNORECASE)
    for match in function_pattern.finditer(text):
        name = match.group(1).strip()
        units.append(
            project_mod._build_st_unit(
                f"{name}.st",
                f"FUNCTION {name} : BOOL\nIMPLEMENTATION\n{name} := TRUE;\n",
            )
        )
    gvl_pattern = re.compile(
        r"//\s*cts:gvl\s+([^:]+):\s*([^\s]+)(?:[ \t]+([^\s\r\n]+))?",
        re.IGNORECASE,
    )
    gvl_members = {}
    for match in gvl_pattern.finditer(text):
        gvl = match.group(1).strip()
        member = match.group(2).strip()
        type_name = (match.group(3) or "INT").strip()
        gvl_members.setdefault(gvl, []).append((member, type_name))
    for gvl, members in gvl_members.items():
        declarations = "\n".join(
            f"    {member} : {type_name};" for member, type_name in members
        )
        units.append(
            project_mod._build_st_unit(
                f"{gvl}.st",
                f"VAR_GLOBAL\n{declarations}\nEND_VAR\n",
            )
        )

    if rule.scope.value == "project":
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
    findings = [item for item in (found or []) if isinstance(item, Finding)]
    for finding in findings:
        adjustment = line_adjustments.get(finding.unit_id)
        if adjustment is None:
            continue
        start_lines, synthetic_prefix_lines = adjustment
        location = finding.location
        if location.line is not None:
            location.line += start_lines - synthetic_prefix_lines
        if location.end_line is not None:
            location.end_line += start_lines - synthetic_prefix_lines
    return findings


_TOP_LEVEL_START = re.compile(
    r"(?m)^\s*(?:PROGRAM\b|FUNCTION_BLOCK\b|FUNCTION\b|METHOD\b|"
    r"INTERFACE\b|VAR_GLOBAL\b)",
    re.IGNORECASE,
)


def _split_snippet_units(text):
    """Split a documentation fence containing several ST objects."""
    matches = list(_TOP_LEVEL_START.finditer(text))
    if len(matches) <= 1:
        return [(0, text)]
    segments = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segments.append((start, text[start:end]))
    return segments

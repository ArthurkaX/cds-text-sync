"""CTS0007 - structural indentation drift in ST implementations."""

from __future__ import annotations

from cds_static_analyzer.capabilities import Capability, Scope
from cds_static_analyzer.rules_api import RuleSpec, finding_in
from cds_static_analyzer.st.body import body
from cts_shared.st.blanking import blank_noise, trim_strings
from cts_shared.st.formatting import scan_indentation


def _scan(raw_lines, clean_lines):
    """Keep the historical private seam while using the shared scanner."""
    return scan_indentation(raw_lines, clean_lines)


def check(unit, ctx):
    """Report indentation that contradicts the actual ST block nesting."""
    ctx.capability(Capability.ST_TEXT)
    if not unit.implementation:
        return

    section = body(unit)
    raw_lines = []
    starts = []
    for _lineno, line_start, line in section.lines():
        raw_lines.append(line)
        starts.append(line_start)
    for index, actual, expected, mixed, prefix, level in _scan(
        raw_lines, section.text.split("\n")
    ):
        if not (mixed or actual != expected):
            continue
        reason = "mixed tabs and spaces" if mixed else (
            f"expected indentation for block level {level}, got {actual}"
        )
        yield finding_in(
            message=f"structural indentation is inconsistent: {reason}",
            unit=unit,
            offset=starts[index],
            end_offset=starts[index] + len(prefix),
            anchor=f"level:{level}",
            context=raw_lines[index].lstrip(),
        )


def _implementation_start(raw_lines):
    """Return the first implementation line in a complete POU document."""
    for index, line in enumerate(raw_lines):
        stripped = line.rstrip("\r")
        if stripped in ("IMPLEMENTATION", "// --- implementation ---") and index != 0:
            start = index + 1
            while start < len(raw_lines) and raw_lines[start].rstrip("\r") == "":
                start += 1
            return start
    return 0


def fix(text, finding):
    """Correct only the implementation lines represented by *finding*."""
    raw_lines = text.split("\n")
    clean_lines = trim_strings(blank_noise(text)).split("\n")
    target_lines = set()
    location = finding.get("location") if isinstance(finding, dict) else None
    if isinstance(location, dict) and location.get("line") is not None:
        start_line = int(location["line"])
        end_line = int(location.get("end_line") or start_line)
        target_lines.update(range(start_line, max(start_line, end_line) + 1))
    for value in (finding.get("member_lines", []) if isinstance(finding, dict) else []):
        try:
            target_lines.add(int(value))
        except (TypeError, ValueError):
            continue
    if not target_lines:
        return text

    implementation_start = _implementation_start(raw_lines)
    records = []
    observed_prefixes = []
    for index, actual, expected, mixed, prefix, _level in _scan(
        raw_lines[implementation_start:], clean_lines[implementation_start:]
    ):
        absolute = implementation_start + index
        if prefix and not mixed:
            observed_prefixes.append(prefix)
        records.append((absolute, actual, expected, mixed, prefix))

    tab_columns = sum(prefix.count("\t") for prefix in observed_prefixes)
    space_columns = sum(prefix.count(" ") for prefix in observed_prefixes)
    use_tabs = tab_columns > space_columns

    def prefix_for(expected):
        if expected <= 0:
            return ""
        for prefix in observed_prefixes:
            if len(prefix.expandtabs(1)) == expected:
                return prefix
        return ("\t" if use_tabs else " ") * expected

    for index, actual, expected, mixed, prefix in records:
        if index + 1 not in target_lines or (actual == expected and not mixed):
            continue
        raw_lines[index] = prefix_for(expected) + raw_lines[index][len(prefix):]
    return "\n".join(raw_lines)


RULE = RuleSpec(
    id="CTS0007",
    title="Structural indentation",
    severity="style",
    scope=Scope.UNIT,
    requires={Capability.ST_TEXT},
    kinds="CALLABLE",
    summary="Implementation indentation must reflect actual ST block nesting.",
    topic="Style",
    check=check,
    merge="adjacent",
    options={"merge": True},
    fix=fix,
)

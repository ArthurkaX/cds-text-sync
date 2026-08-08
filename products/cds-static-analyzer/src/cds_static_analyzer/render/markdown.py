"""
markdown.py - Markdown rendering of an AnalysisResult.

Gives ``cts analyze --format md`` a real markdown document instead of the
terminal renderer's ANSI-oriented text. Deterministic: findings and
diagnostics keep the order the result already carries; the renderer never
re-sorts.
"""

from __future__ import annotations


def _cell(text):
    """Escape one table cell so ``|`` or a newline cannot break the table."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(result):
    """Render an AnalysisResult as a markdown document."""
    lines = []
    lines.append("# cts analyze")
    lines.append("")

    summary = result.summary
    counts = ", ".join(f"{n} {sev}" for sev, n in summary.by_severity.items() if n)
    lines.append(
        f"**{summary.total} findings** ({counts or 'none'}) · "
        f"{len(result.diagnostics)} diagnostics"
    )
    if summary.suppressed:
        lines.append(f"{summary.suppressed} findings suppressed")
    if summary.baselined:
        lines.append(f"{summary.baselined} findings baselined")
    if summary.stale_suppressions:
        lines.append(
            f"{len(summary.stale_suppressions)} stale suppression(s) no "
            "longer match any finding"
        )
    lines.append("")

    if not result.findings:
        lines.append("No findings.")
        lines.append("")
    else:
        # Group by file, preserving first-appearance order.
        by_file = {}
        for f in result.findings:
            by_file.setdefault(f.location.path or "-", []).append(f)

        for path, findings in by_file.items():
            lines.append(f"## {_cell(path)}")
            lines.append("")
            lines.append("| line | rule | severity | message |")
            lines.append("| --- | --- | --- | --- |")
            for f in findings:
                loc = f.location
                line = loc.line if loc.line is not None else "-"
                if loc.end_line and loc.end_line != loc.line:
                    line = f"{line}-{loc.end_line}"
                lines.append(
                    f"| {line} | {_cell(f.rule_id)} | {_cell(f.severity)} "
                    f"| {_cell(f.message)} |"
                )
            lines.append("")

    if result.diagnostics:
        lines.append("## Diagnostics")
        lines.append("")
        lines.append("| path | kind | message |")
        lines.append("| --- | --- | --- |")
        for d in result.diagnostics:
            loc = d.location
            path = loc.path or "-"
            line = loc.line if loc.line is not None else ""
            path_cell = f"{path}:{line}" if line else path
            rule = f"{d.rule_id}: " if d.rule_id else ""
            lines.append(
                f"| {_cell(path_cell)} | {_cell(d.kind)} | "
                f"{_cell(rule + d.message)} |"
            )
        lines.append("")

    return "\n".join(lines)

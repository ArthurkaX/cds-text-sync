"""
terminal.py - Human-readable rendering of an AnalysisResult.
"""

from __future__ import annotations

_SEVERITY_LABEL = {
    "danger": "danger",
    "suspicious": "suspicious",
    "style": "style",
}


def render(result):
    """Render a result for a person reading a terminal."""
    lines = []
    if result.findings:
        for f in result.findings:
            loc = f.location
            pos = ""
            if loc.path:
                line = loc.line or "?"
                if loc.end_line and loc.end_line != loc.line:
                    line = f"{loc.line}-{loc.end_line}"
                pos = f"{loc.path}:{line}:{loc.column or '?'}  "
            sev = _SEVERITY_LABEL.get(f.severity, f.severity)
            line = f"[{f.rule_id}] {sev}  {pos}{f.message}"
            if f.member_count:
                line += f" (x{f.member_count})"
            lines.append(line)
            if f.unit_id and f.unit_id != loc.path:
                lines.append(f"          unit: {f.unit_id}")
    else:
        lines.append("no findings")

    if result.diagnostics:
        lines.append("")
        lines.append("diagnostics (analysis could not provide a declared capability):")
        for d in result.diagnostics:
            loc = d.location
            pos = f"{loc.path}:{loc.line or '?'}" if loc.path else "-"
            tag = f"[{d.rule_id}] " if d.rule_id else ""
            lines.append(f"  {pos}  {tag}{d.kind}: {d.message}")

    summary = result.summary
    lines.append("")
    counts = ", ".join(f"{n} {sev}" for sev, n in summary.by_severity.items() if n)
    state = "complete" if result.complete else "INCOMPLETE"
    lines.append(
        f"{summary.total} findings ({counts or 'none'}) · "
        f"{len(result.diagnostics)} diagnostics · {state}"
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
    return "\n".join(lines) + "\n"

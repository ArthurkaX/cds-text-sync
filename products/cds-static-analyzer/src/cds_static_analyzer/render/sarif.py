"""
sarif.py - SARIF 2.1.0 rendering of an AnalysisResult.

SARIF gives GitHub Code Scanning a native renderer: findings appear in the
PR diff without a separate integration. Built on the same Finding model as
the JSON and text renderers.
"""

from __future__ import annotations

import json

_LEVEL = {
    "danger": "error",
    "suspicious": "warning",
    "style": "note",
}


def render(result, tool_name="cts analyze", tool_version="1"):
    """Render an AnalysisResult as a SARIF 2.1.0 document."""
    rules = {}
    for f in result.findings:
        if f.rule_id not in rules:
            rules[f.rule_id] = {
                "id": f.rule_id,
                "name": f.rule_title or f.rule_id,
                "shortDescription": {"text": f.rule_title or f.rule_id},
                "defaultConfiguration": {"level": _LEVEL.get(f.severity, "warning")},
            }

    results = []
    for f in result.findings:
        entry = {
            "ruleId": f.rule_id,
            "level": _LEVEL.get(f.severity, "warning"),
            "message": {"text": f.message},
        }
        if f.fingerprint:
            entry["partialFingerprints"] = {"ctsAnalyzeFingerprint": f.fingerprint}
        loc = f.location
        if loc.path:
            region = {}
            if loc.line is not None:
                region["startLine"] = loc.line
            if loc.column is not None:
                region["startColumn"] = loc.column
            if loc.end_line is not None:
                region["endLine"] = loc.end_line
            if loc.end_column is not None:
                region["endColumn"] = loc.end_column
            entry["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": loc.path},
                        "region": region,
                    }
                }
            ]
        results.append(entry)

    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "rules": sorted(rules.values(), key=lambda r: r["id"]),
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": result.complete,
                        "toolExecutionNotifications": [
                            {
                                "level": "warning",
                                "message": {"text": d.message},
                                "descriptor": {"id": d.kind},
                            }
                            for d in result.diagnostics
                        ],
                    }
                ],
            }
        ],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

"""
sarif.py - SARIF 2.1.0 rendering of an AnalysisResult.

SARIF gives GitHub Code Scanning a native renderer: findings appear in the
PR diff without a separate integration. Built on the same Finding model as
the JSON and text renderers.
"""

from __future__ import annotations

import json

import cds_static_analyzer as analyze

_LEVEL = {
    "danger": "error",
    "suspicious": "warning",
    "style": "note",
}


def _rule_metadata():
    """Map {rule_id: {summary, topic, scope}} from the built-in registry.

    The registry lives in the same package and is expected to load, but a
    renderer must never be able to break a run: after a successful analysis a
    raise here would lose the whole result. Any failure degrades gracefully
    to an empty map and the document falls back to today's leaner rule
    entries.
    """
    try:
        from cds_static_analyzer.registry import load_builtin_rules

        registry = load_builtin_rules()
    except Exception:
        return {}
    meta = {}
    for rule_id, rule in registry.items():
        meta[rule_id] = {
            "summary": rule.summary,
            "topic": rule.topic,
            "scope": rule.scope.value,
        }
    return meta


def render(result, tool_name="cts analyze", tool_version=None):
    """Render an AnalysisResult as a SARIF 2.1.0 document."""
    if tool_version is None:
        tool_version = analyze.__version__
    metadata = _rule_metadata()
    rules = {}
    for f in result.findings:
        if f.rule_id not in rules:
            entry = {
                "id": f.rule_id,
                "name": f.rule_title or f.rule_id,
                "shortDescription": {"text": f.rule_title or f.rule_id},
                "defaultConfiguration": {"level": _LEVEL.get(f.severity, "warning")},
            }
            meta = metadata.get(f.rule_id)
            if meta:
                summary = meta["summary"] or f.rule_title or f.rule_id
                entry["fullDescription"] = {"text": summary}
                # help is the rule's long-form explanation. Note: there is no
                # canonical public URL for this tool, so no informationUri or
                # helpUri is emitted - do not "fix" that by inventing one.
                entry["help"] = {"text": summary}
                entry["properties"] = {
                    "topic": meta["topic"],
                    "scope": meta["scope"],
                }
            rules[f.rule_id] = entry

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

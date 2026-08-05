"""
fingerprint.py - Stable identity of a Finding.

A finding's identity must survive reindentation and line insertion, or the
baseline and every suppression reason are invalidated by the first reformat.
The fingerprint therefore mixes:

* the fingerprint schema version (migration-tested before any baseline),
* the rule id,
* the stable UnitId (relative path + qualified name),
* a rule-specific semantic anchor (e.g. the input member name),
* a normalised context hash.

Path and line/column never take part in identity.
"""

from __future__ import annotations

import hashlib
import json

from cds_static_analyzer.model import normalize_context

FINGERPRINT_SCHEMA = 1


def fingerprint(rule_id, unit_id, anchor, context="", schema=FINGERPRINT_SCHEMA):
    """Compute a stable fingerprint string for one finding."""
    payload = {
        "schema": schema,
        "rule": rule_id,
        "unit": unit_id,
        "anchor": anchor or "",
        "context": normalize_context(context or ""),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"cts{schema}:{digest[:40]}"

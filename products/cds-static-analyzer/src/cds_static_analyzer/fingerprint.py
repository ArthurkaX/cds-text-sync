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

Several findings of one rule can still share all of the above - two identical
statements at the same block level, say - and would then be indistinguishable.
Duplicates past the first therefore carry an occurrence number.  The first
occurrence keeps the plain payload, so its fingerprint is unchanged by this
mechanism and existing baselines survive; only the previously unaddressable
duplicates get a new identity.
"""

from __future__ import annotations

import hashlib
import json

from cds_static_analyzer.model import normalize_context

FINGERPRINT_SCHEMA = 1


def fingerprint(rule_id, unit_id, anchor, context="", schema=FINGERPRINT_SCHEMA, occurrence=0):
    """Compute a stable fingerprint string for one finding.

    ``occurrence`` numbers exact duplicates in document order.  It is omitted
    from the payload when zero, which keeps the first occurrence byte-identical
    to what this function returned before duplicates were disambiguated.
    """
    payload = {
        "schema": schema,
        "rule": rule_id,
        "unit": unit_id,
        "anchor": anchor or "",
        "context": normalize_context(context or ""),
    }
    if occurrence:
        payload["occurrence"] = int(occurrence)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"cts{schema}:{digest[:40]}"

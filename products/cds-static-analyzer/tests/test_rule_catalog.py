"""The published rule catalog must not drift from the registry.

``rules/implemented_rules.md`` is what a user reads to decide whether the
analyzer covers their concern, and it ships inside the wheel.  Nothing
generated it, so a new rule silently missing from it is invisible until
someone notices the list is short.
"""

from __future__ import annotations

import re
from pathlib import Path

from cds_static_analyzer.registry import load_builtin_rules

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "cds_static_analyzer"
    / "rules"
    / "implemented_rules.md"
)

_ENTRY = re.compile(r"^-\s+(CTS\d{4})\s+[-—]\s+(.+?)\s*$")


def _implemented_section():
    """Lines of the leading section, before the ``Pending`` backlog headings.

    The file doubles as the backlog, and a pending item may well mention a
    rule id in prose ("covered by CTS0045"), so the guard must look only at
    the implemented list.
    """
    lines = []
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            break
        lines.append(line)
    return lines


def _catalog_entries():
    entries = {}
    for line in _implemented_section():
        match = _ENTRY.match(line)
        if match:
            entries[match.group(1)] = match.group(2)
    return entries


def test_catalog_lists_exactly_the_registered_rules():
    entries = _catalog_entries()
    registered = set(load_builtin_rules())
    assert set(entries) == registered, {
        "missing_from_catalog": sorted(registered - set(entries)),
        "stale_catalog_entries": sorted(set(entries) - registered),
    }


def test_catalog_has_no_duplicate_or_malformed_lines():
    bullets = [line for line in _implemented_section() if line.startswith("- ")]
    parsed = [line for line in bullets if _ENTRY.match(line)]
    assert bullets == parsed, [line for line in bullets if line not in parsed]
    ids = [_ENTRY.match(line).group(1) for line in parsed]
    assert len(ids) == len(set(ids)), sorted(
        {rule_id for rule_id in ids if ids.count(rule_id) > 1}
    )

"""
model.py - Result model for ``cts analyze``.

The analyzer distinguishes two kinds of output items, on purpose:

* ``Finding``  - a problem in the project (a rule fired).
* ``Diagnostic`` - the analysis itself could not provide a declared
  capability for some part of the project (file unreadable, git base
  missing, XML unparsable, ...).

A run that can only deliver partial results is not silently "clean": it
carries ``complete == False`` and one or more Diagnostics. A Finding and a
Diagnostic are both rendered, but they answer different questions.

The JSON envelope is versioned from day one:

    {
      "schema_version": 1,
      "complete": true,
      "findings": [],
      "diagnostics": [],
      "summary": {}
    }

Determinism: findings and diagnostics are sorted by
``path -> position -> rule_id -> fingerprint`` before rendering.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

DANGER = "danger"
SUSPICIOUS = "suspicious"
STYLE = "style"

_SEVERITY_ORDER = {DANGER: 0, SUSPICIOUS: 1, STYLE: 2}
SEVERITIES = (DANGER, SUSPICIOUS, STYLE)


def severity_rank(severity: str) -> int:
    """Return an int rank: lower is more severe."""
    return _SEVERITY_ORDER.get(severity, 3)


def is_valid_severity(value: str) -> bool:
    return value in _SEVERITY_ORDER


# ---------------------------------------------------------------------------
# Location / spans
# ---------------------------------------------------------------------------


class Location:
    """A position in a project-view file.

    ``path`` is relative to the project-view root, forward slashes.
    ``line``/``column`` are 1-based and are display-only: they never take
    part in a finding's identity. ``offset``/``end_offset`` are byte offsets
    into the unit's own text (0-based).
    """

    def __init__(
        self,
        path,
        line=None,
        column=None,
        end_line=None,
        end_column=None,
        offset=None,
        end_offset=None,
    ):
        self.path = path
        self.line = line
        self.column = column
        self.end_line = end_line
        self.end_column = end_column
        self.offset = offset
        self.end_offset = end_offset

    def to_dict(self):
        data = {"path": self.path}
        if self.line is not None:
            data["line"] = self.line
        if self.column is not None:
            data["column"] = self.column
        if self.end_line is not None:
            data["end_line"] = self.end_line
        if self.end_column is not None:
            data["end_column"] = self.end_column
        return data

    @property
    def sort_key(self):
        return (
            self.path or "",
            self.line if self.line is not None else 0,
            self.column if self.column is not None else 0,
        )

    def __repr__(self):
        return f"<Location {self.path}:{self.line}:{self.column}>"


def line_col_of(text: str, offset):
    """Compute (line, column) of *offset* in *text*, both 1-based.

    ``offset`` may be None -> (None, None).
    """
    if offset is None:
        return None, None
    if offset < 0:
        offset = 0
    if offset > len(text):
        offset = len(text)
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - last_nl  # 1-based column
    return line, col


# ---------------------------------------------------------------------------
# Finding / Diagnostic
# ---------------------------------------------------------------------------


class Finding:
    """A problem in the project reported by a rule."""

    def __init__(
        self,
        rule_id,
        severity,
        message,
        location=None,
        unit_id=None,
        anchor=None,
        context=None,
        rule_title=None,
    ):
        self.rule_id = rule_id
        self.rule_title = rule_title or ""
        self.severity = severity
        self.message = message
        self.location = location or Location("")
        self.unit_id = unit_id
        self.anchor = anchor
        self.context = context
        self.fingerprint: str | None = None  # assigned by the runner

    def to_dict(self, with_fingerprint=True):
        data = {
            "rule_id": self.rule_id,
            "rule_title": self.rule_title,
            "severity": self.severity,
            "message": self.message,
            "location": self.location.to_dict(),
        }
        if self.unit_id:
            data["unit_id"] = self.unit_id
        if self.anchor:
            data["anchor"] = self.anchor
        if self.context:
            data["context"] = self.context
        if with_fingerprint and self.fingerprint:
            data["fingerprint"] = self.fingerprint
        return data

    def __repr__(self):
        return (
            f"<Finding {self.rule_id} {self.severity} "
            f"{self.location.path}:{self.location.line}>"
        )


class Diagnostic:
    """Analysis could not provide a declared capability."""

    def __init__(self, kind, message, location=None, rule_id=None, unit_id=None):
        self.kind = kind
        self.message = message
        self.location = location or Location("")
        self.rule_id = rule_id
        self.unit_id = unit_id

    def to_dict(self):
        data = {
            "kind": self.kind,
            "message": self.message,
            "location": self.location.to_dict(),
        }
        if self.rule_id:
            data["rule_id"] = self.rule_id
        if self.unit_id:
            data["unit_id"] = self.unit_id
        return data

    def __repr__(self):
        return f"<Diagnostic {self.kind} {self.location.path}>"


# ---------------------------------------------------------------------------
# Summary + result envelope
# ---------------------------------------------------------------------------


class Summary:
    def __init__(self):
        self.files = 0
        self.total = 0
        self.by_severity = {DANGER: 0, SUSPICIOUS: 0, STYLE: 0}
        self.by_rule = {}
        self.suppressed = 0
        self.suppressed_by_directive = 0
        self.baselined = 0
        self.stale_suppressions = []
        self.stale_baselined = []
        self.rules_run = []
        self.diagnostics = 0

    def add_finding(self, finding):
        self.total += 1
        self.by_severity[finding.severity] = (
            self.by_severity.get(finding.severity, 0) + 1
        )
        self.by_rule[finding.rule_id] = self.by_rule.get(finding.rule_id, 0) + 1

    def to_dict(self):
        return {
            "files": self.files,
            "total": self.total,
            "by_severity": self.by_severity,
            "by_rule": self.by_rule,
            "suppressed": self.suppressed,
            "suppressed_by_directive": self.suppressed_by_directive,
            "baselined": self.baselined,
            "stale_suppressions": list(self.stale_suppressions),
            "stale_baselined": list(self.stale_baselined),
            "rules_run": list(self.rules_run),
            "diagnostics": self.diagnostics,
        }


class AnalysisResult:
    """The full, deterministic result of one analysis run."""

    def __init__(self):
        self.schema_version = SCHEMA_VERSION
        self.complete = True
        self.findings = []
        self.diagnostics = []
        self.summary = Summary()

    def sort(self):
        """Deterministic order: path -> position -> rule_id -> fingerprint."""

        def fkey(f):
            loc = f.location.sort_key
            return (
                loc[0],
                loc[1],
                loc[2],
                f.rule_id,
                f.fingerprint or "",
                f.message,
            )

        def dkey(d):
            loc = d.location.sort_key
            return (loc[0], loc[1], loc[2], d.kind, d.message)

        self.findings.sort(key=fkey)
        self.diagnostics.sort(key=dkey)

    def to_dict(self):
        self.sort()
        return {
            "schema_version": self.schema_version,
            "complete": self.complete,
            "findings": [f.to_dict() for f in self.findings],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "summary": self.summary.to_dict(),
        }


def normalize_context(text: str) -> str:
    """Normalise a fragment for fingerprinting: comments are expected to be
    gone already; collapse whitespace and case (ST is case-insensitive)."""
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed.lower()

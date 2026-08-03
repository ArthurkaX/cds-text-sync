"""
triage.py - Converting findings into suppress / fix-later decisions.

``cts analyze triage --apply decisions.json`` is the scriptable half of
triage: an agent prepares decisions, a human approves, the tool applies them
after validating the complete decision batch. Each resulting state file is
written atomically. The interactive TUI comes later; this batch mode is the
part that is testable and CI-usable.

A decision is one object in a JSON list:

    {"fingerprint": "cts1:...", "action": "suppress",
     "reason": "read by a method outside this project-view"}
    {"fingerprint": "cts1:...", "action": "fix-later", "note": "TICKET-77"}

Actions:

* ``suppress``  - writes to suppressions.toml (reason mandatory);
* ``fix-later`` - records the decision in the resumable session file;
* ``baseline``  - folds the finding into the baseline.

Unrecognised fingerprints are errors: a decision must point at a finding that
actually exists in this run.
"""

from __future__ import annotations

import json
import os

from cds_text_sync.analyze.state import (
    baseline_fingerprints,
    baseline_created,
    read_baseline,
    read_session,
    read_suppressions,
    suppressions_path,
    write_baseline,
    write_session,
    write_suppressions,
)

VALID_ACTIONS = ("suppress", "fix-later", "baseline")


class TriageError(Exception):
    """Decisions file is malformed or references unknown findings."""


def load_decisions(path):
    if not path:
        raise TriageError("no decisions file given (--apply <file>)")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise TriageError(f"cannot read decisions file {path}: {exc}") from exc
    if not isinstance(data, list):
        raise TriageError("decisions file must be a JSON list")
    out = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise TriageError(f"decisions[{idx}]: not an object")
        action = str(item.get("action", "")).strip()
        if action not in VALID_ACTIONS:
            raise TriageError(
                f"decisions[{idx}]: action must be one of "
                f"{','.join(VALID_ACTIONS)}, got {action!r}"
            )
        fingerprint = str(item.get("fingerprint", "")).strip()
        if not fingerprint:
            raise TriageError(f"decisions[{idx}]: missing fingerprint")
        if action == "suppress" and not str(item.get("reason", "")).strip():
            raise TriageError(f"decisions[{idx}]: suppress needs a non-empty reason")
        out.append(
            {
                "fingerprint": fingerprint,
                "action": action,
                "reason": str(item.get("reason", "")).strip(),
                "note": str(item.get("note", "")).strip(),
                "rule_id": str(item.get("rule_id", "")).strip(),
                "unit_id": str(item.get("unit_id", "")).strip(),
            }
        )
    return out


def apply_decisions(workspace, result, decisions):
    """Apply decisions to state. Writes nothing on validation failure."""
    current = {f.fingerprint for f in result.findings}

    for decision in decisions:
        if decision["fingerprint"] not in current:
            raise TriageError(
                f"decision {decision['fingerprint']} does not match any "
                "finding in this run"
            )

    state_dir = workspace.state_dir
    suppressions = read_suppressions(state_dir)
    session = read_session(state_dir)
    baseline_entries, _ = read_baseline(state_dir)

    known_suppressed = suppression_set(suppressions)
    known_baselined = baseline_fingerprints(baseline_entries)
    existing_session = {d.get("fingerprint") for d in session.get("decisions", [])}

    for decision in decisions:
        fingerprint = decision["fingerprint"]
        if decision["action"] == "suppress":
            if fingerprint in known_suppressed:
                continue  # already suppressed
            suppressions.append(
                {
                    "fingerprint": fingerprint,
                    "rule_id": decision["rule_id"],
                    "unit_id": decision["unit_id"],
                    "reason": decision["reason"],
                    "until": "",
                }
            )
            known_suppressed.add(fingerprint)
        elif decision["action"] == "baseline":
            if fingerprint in known_baselined:
                continue
            finding = next(f for f in result.findings if f.fingerprint == fingerprint)
            baseline_entries.append(
                {
                    "fingerprint": fingerprint,
                    "rule_id": finding.rule_id,
                    "unit_id": finding.unit_id or "",
                    "message": finding.message,
                }
            )
            known_baselined.add(fingerprint)
        else:  # fix-later
            if fingerprint in existing_session:
                continue
            session["decisions"].append(
                {
                    "fingerprint": fingerprint,
                    "action": "fix-later",
                    "note": decision["note"],
                }
            )
            existing_session.add(fingerprint)

    # Write only after every decision has been validated and applied in memory.
    if suppressions or os.path.isfile(suppressions_path(state_dir)):
        write_suppressions(state_dir, suppressions)
    if baseline_entries:
        write_baseline(
            state_dir,
            baseline_entries,
            created=baseline_created(state_dir),
        )
    write_session(state_dir, session.get("decisions", []))
    return {
        "suppressed": _count(decisions, "suppress"),
        "baselined": _count(decisions, "baseline"),
        "fix_later": _count(decisions, "fix-later"),
    }


def suppression_set(suppressions):
    return {e["fingerprint"] for e in suppressions}


def _count(decisions, action):
    return sum(1 for d in decisions if d["action"] == action)

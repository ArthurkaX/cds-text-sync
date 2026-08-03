"""
state.py - Analyzer state living next to ``project-view/``.

State is never written inside ``project-view/`` (that tree is owned by the
sync engine). It lives in ``<sync-folder>/.cts-analyze/``:

* ``baseline.json``     - machine-written lock file: sorted, one entry per
                          line for friendly diffs; hands are off
* ``suppressions.toml`` - human + triage written; every entry carries a
                          mandatory ``reason``
* ``session.json``      - resumable triage session; written atomically

Each individual file write is atomic (temp file + ``os.replace``). Triage
validates the complete decision set before writing its separate state files;
multi-file recovery is intentionally left to a future transaction journal.
"""

from __future__ import annotations

import datetime as _dt
import json
import os

from cds_text_sync.analyze.config import tomllib
from cds_text_sync.analyze.fingerprint import FINGERPRINT_SCHEMA

STATE_SCHEMA = 1

BASELINE_FILENAME = "baseline.json"
SUPPRESSIONS_FILENAME = "suppressions.toml"
SESSION_FILENAME = "session.json"


class StateError(Exception):
    """State file is missing, unreadable, or malformed."""


# ---------------------------------------------------------------------------
# Atomic IO
# ---------------------------------------------------------------------------


def write_json_atomic(path, data, pretty=True):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    write_text_atomic(path, text)


def write_text_atomic(path, text):
    """Write UTF-8 text through the common temp-file/replace path."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise StateError(f"cannot read {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def baseline_path(state_dir):
    return os.path.join(state_dir, BASELINE_FILENAME)


def read_baseline(state_dir):
    """Return (entries, fingerprint_schema). entries is a list of dicts."""
    data = read_json(baseline_path(state_dir), default=None)
    if data is None:
        return [], FINGERPRINT_SCHEMA
    if not isinstance(data, dict):
        raise StateError(f"{baseline_path(state_dir)}: not an object")
    entries = data.get("entries", []) or []
    if not isinstance(entries, list):
        raise StateError(f"{baseline_path(state_dir)}: entries is not a list")
    raw_schema = data.get("fingerprint_schema")
    if raw_schema is None:
        schema = FINGERPRINT_SCHEMA
    else:
        try:
            schema = int(raw_schema)
        except (TypeError, ValueError):
            raise StateError(
                f"{baseline_path(state_dir)}: bad fingerprint_schema {raw_schema!r}"
            ) from None
    return entries, schema


def baseline_created(state_dir):
    """Return the existing baseline creation timestamp, if present."""
    data = read_json(baseline_path(state_dir), default=None)
    if isinstance(data, dict):
        return data.get("created")
    return None


def validate_baseline_schema(state_dir):
    """Raise StateError when the baseline's fingerprint schema is unsupported.

    The explicit ``fingerprint_schema`` field is validated, never inferred
    from fingerprint string prefixes. A baseline without the field is
    treated as the supported schema (the schema in use when baselines were
    introduced); a missing baseline is fine.
    """
    data = read_json(baseline_path(state_dir), default=None)
    if data is None:
        return
    if not isinstance(data, dict):
        raise StateError(f"{baseline_path(state_dir)}: not an object")
    raw_schema = data.get("fingerprint_schema")
    if raw_schema is None:
        return
    try:
        schema = int(raw_schema)
    except (TypeError, ValueError):
        raise StateError(
            f"{baseline_path(state_dir)}: bad fingerprint_schema {raw_schema!r}"
        ) from None
    if schema != FINGERPRINT_SCHEMA:
        raise StateError(
            f"baseline fingerprint schema {schema} is unsupported; run "
            "'cts analyze baseline update'"
        )


def write_baseline(state_dir, entries, created=None, updated=None):
    """Write a baseline. One entry per line for a friendly diff."""
    entries = sorted(
        entries, key=lambda e: (e.get("fingerprint", ""), e.get("rule_id", ""))
    )
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    data = {
        "schema_version": STATE_SCHEMA,
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "created": created or now,
        "updated": updated or now,
        "entries": entries,
    }
    path = baseline_path(state_dir)
    lines = [
        "{",
        f'  "schema_version": {STATE_SCHEMA},',
        f'  "fingerprint_schema": {FINGERPRINT_SCHEMA},',
        f'  "created": {json.dumps(data["created"])},',
        f'  "updated": {json.dumps(data["updated"])},',
        '  "entries": [',
    ]
    for i, entry in enumerate(entries):
        comma = "," if i < len(entries) - 1 else ""
        lines.append(
            "    " + json.dumps(entry, sort_keys=True, ensure_ascii=False) + comma
        )
    lines.extend(["  ]", "}"])
    write_text_atomic(path, "\n".join(lines) + "\n")
    return data


def baseline_fingerprints(entries):
    return {e["fingerprint"] for e in entries if e.get("fingerprint")}


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------


def suppressions_path(state_dir):
    return os.path.join(state_dir, SUPPRESSIONS_FILENAME)


def read_suppressions(state_dir):
    """Read suppressions as a list of dicts. Missing file -> []."""
    path = suppressions_path(state_dir)
    if not os.path.isfile(path):
        return []
    if tomllib is None:
        raise StateError(f"{path} requires Python 3.11+ (tomllib) to read")
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StateError(f"cannot parse {path}: {exc}") from exc
    raw = data.get("suppress", []) or []
    entries = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("fingerprint"):
            raise StateError(f"{path}: suppress[{idx}] needs a fingerprint")
        if not item.get("reason", "").strip():
            raise StateError(f"{path}: suppress[{idx}] needs a non-empty reason")
        entries.append(
            {
                "fingerprint": str(item["fingerprint"]),
                "rule_id": str(item.get("rule_id", "")),
                "unit_id": str(item.get("unit_id", "")),
                "reason": str(item["reason"]),
                "until": str(item.get("until", "")),
            }
        )
    return entries


def write_suppressions(state_dir, entries):
    """Write suppressions back (used by ``triage --apply``)."""
    path = suppressions_path(state_dir)
    lines = [
        "# Suppressions for cts analyze. Every entry needs a reason;",
        "# empty reasons are rejected on read.",
        "",
    ]
    for e in entries:
        lines.append("[[suppress]]")
        lines.append(f"fingerprint = {json.dumps(e['fingerprint'])}")
        if e.get("rule_id"):
            lines.append(f"rule_id = {json.dumps(e['rule_id'])}")
        if e.get("unit_id"):
            lines.append(f"unit_id = {json.dumps(e['unit_id'])}")
        lines.append(f"reason = {json.dumps(e['reason'])}")
        if e.get("until"):
            lines.append(f"until = {json.dumps(e['until'])}")
        lines.append("")
    write_text_atomic(path, "\n".join(lines))


def suppression_fingerprints(entries):
    return {e["fingerprint"] for e in entries}


def is_expired(entry, today=None):
    """True when the suppression's ``until`` date has passed."""
    until = entry.get("until", "").strip()
    if not until:
        return False
    if today is None:
        today = _dt.date.today()
    try:
        until_date = _dt.date.fromisoformat(until)
    except ValueError:
        return False  # unparseable dates do not expire silently
    return until_date < today


# ---------------------------------------------------------------------------
# Triage session
# ---------------------------------------------------------------------------


def session_path(state_dir):
    return os.path.join(state_dir, SESSION_FILENAME)


def read_session(state_dir):
    data = read_json(session_path(state_dir), default=None)
    if data is None:
        return {"decisions": []}
    if not isinstance(data, dict):
        raise StateError(f"{session_path(state_dir)}: not an object")
    return data


def write_session(state_dir, decisions):
    data = {
        "schema_version": STATE_SCHEMA,
        "decisions": decisions,
    }
    write_json_atomic(session_path(state_dir), data)

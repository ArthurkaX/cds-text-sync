# -*- coding: utf-8 -*-
"""Parse generated ``CTS|`` event lines out of a CODESYS runtime log.

The generated PLC code logs one event per CmpLog entry as::

    CTS|<level>|<CODE>|<TAG>|k=v;k=v

``level`` is ``M`` (minimal, always on) or ``V`` (verbose), ``CODE`` matches
``[A-Z0-9_]+``, ``TAG`` is an equipment/signal tag and may be empty, and the
payload is optional. The generator guarantees keys match ``[A-Za-z0-9_.]+``
and values never contain ``|`` or ``;``.

A runtime log line wraps that message in the CODESYS header
``<timestamp>, <CmpId>, <ClassId>, <ErrorId>, <InfoId>, <message>`` -- see the
real sample ``2026-04-22T18:23:47.110Z, 0x00008005, 1, 1, 0, CTS|M|...`` -- but
this module stays tolerant: the ``CTS|`` marker may sit anywhere in the line
and the timestamp is taken from the leading field only when it parses. A line
that carries the marker but does not parse is kept with ``parse_error`` set
rather than dropped.

Pure functions only, so the format can be unit-tested without a daemon.
"""

from __future__ import annotations

import re

CTS_MARKER = "CTS|"

# Leading timestamp of a CODESYS runtime log line. Accepts the ISO form the
# Linux runtime writes (``2026-04-22T18:23:47.110Z``) and the space-separated
# form older Windows runtimes wrote (``22.04.2026 18:23:47`` is not covered --
# that is not ISO, so such a line keeps an empty ``time``).
_TIMESTAMP_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?\s*Z?)"
)

_LEVELS = ("M", "V")
_CODE_RE = re.compile(r"^[A-Z0-9_]+$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.]+$")


def _record(time, level="", code="", tag="", fields=None, raw=""):
    return {
        "time": time,
        "level": level,
        "code": code,
        "tag": tag,
        "fields": fields if fields is not None else {},
        "raw": raw,
    }


def parse_cts_line(line):
    """Return one parsed record for a line carrying ``CTS|``, else ``None``.

    Unparseable CTS lines are returned too, with a ``parse_error`` string that
    lists every problem found. Non-CTS lines return ``None``.
    """
    text = line.rstrip("\r\n")
    idx = text.find(CTS_MARKER)
    if idx < 0:
        return None

    match = _TIMESTAMP_RE.match(text)
    time = match.group(1) if match else ""

    payload = text[idx + len(CTS_MARKER) :]
    parts = payload.split("|", 3)
    if len(parts) < 2:
        return _fail(
            _record(time, level=parts[0].strip(), raw=text),
            "missing level/code",
        )

    level = parts[0].strip()
    code = parts[1].strip()
    tag = parts[2] if len(parts) >= 3 else ""
    rest = parts[3] if len(parts) >= 4 else ""

    problems = []
    if level not in _LEVELS:
        problems.append("level %r is not M or V" % level)
    if not _CODE_RE.match(code):
        problems.append("code %r is not [A-Z0-9_]+" % code)

    fields = {}
    for chunk in rest.split(";"):
        if not chunk:
            continue
        if "=" not in chunk:
            problems.append("field %r has no '='" % chunk)
            continue
        key, value = chunk.split("=", 1)
        if not _KEY_RE.match(key):
            problems.append("key %r is not [A-Za-z0-9_.]+" % key)
            continue
        if "|" in value:
            problems.append("value for %r contains '|'" % key)
            continue
        fields[key] = value

    record = _record(time, level=level, code=code, tag=tag, fields=fields, raw=text)
    if problems:
        record["parse_error"] = "; ".join(problems)
    return record


def _fail(record, reason):
    record["parse_error"] = reason
    return record


def parse_cts_lines(lines):
    """Parse an iterable of lines, returning only the CTS records."""
    records = []
    for line in lines:
        record = parse_cts_line(line)
        if record is not None:
            records.append(record)
    return records


def filter_records(records, level="", code=""):
    """Apply the --level / --code filters.

    A malformed record has no trustworthy level or code, so it is always kept
    -- the whole point of ``parse_error`` is that bad lines stay visible (and
    they are counted in the response) instead of vanishing behind a filter.
    """
    kept = []
    for record in records:
        if not record.get("parse_error"):
            if level and record.get("level") != level:
                continue
            if code and record.get("code") != code:
                continue
        kept.append(record)
    return kept

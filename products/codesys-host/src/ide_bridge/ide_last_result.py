# -*- coding: utf-8 -*-
"""ide_last_result.py — keep the result of a command the CLI never received.

T50: when the CLI times out it gives up on the pipe, but the daemon does not
give up on the command -- it finishes, then finds its end of the pipe closed
and fails to write the response (Errno 232). The created/updated/failed lists
and the saved flag are gone, and a command that did its work looks exactly
like a command that hung. The user cannot tell "the import failed" from "the
import succeeded and I did not hear about it".

So the daemon writes the outcome of a sync command -- and of any command whose
response write failed -- to ``<sync folder>/.dump/last-result.json``, and
``cts last-result`` reads it back. The request id the CLI put on the command is
stored and logged with it, so a timeout message, a daemon log line and this
file can be matched to each other.

Written with the same atomic replace as the import attestation next to it, so
a reader never sees a half-written file.
"""

from __future__ import print_function

import io
import json
import os

import ide_time
from ide_daemon_state import _log


def _sync_folder():
    """``(folder, error)`` from the daemon helpers, never raising.

    Imported lazily: this module is imported by handlers that tests load with
    ``ide_daemon_helpers`` stubbed out, and a hard import would fail there.
    """
    try:
        from ide_daemon_helpers import _get_sync_folder

        return _get_sync_folder()
    except Exception as exc:
        return None, str(exc)

#: Commands whose outcome is worth keeping even when it was delivered: they run
#: for a long time, produce a result the user acts on, and are the ones a CLI
#: timeout is most likely to lose.
ALWAYS_RECORD = (
    "sync_import_text",
    "sync_import",
    "sync_export_text",
    "sync_export",
    "sync_compare_text",
    "sync_compare",
    "build",
)

RESULT_FILE_NAME = "last-result.json"
#: Written when an import is *refused* (the IDE is online), cleared when an
#: import succeeds.  `cts build` reads it so "The application is up to date"
#: is not mistaken for "the disk changes reached the IDE": a refused import
#: leaves the IDE exactly as it was, and the build then compiles that.
IMPORT_REFUSED_FILE_NAME = "last-import-refused.json"
SCHEMA_VERSION = 1


def write_json_atomic(path, payload):
    """Write JSON to *path* so a reader sees either the old file or the new one.

    IronPython 2.7 has no ``os.replace``; the remove-then-rename fallback is
    not atomic there, but the window is one local rename and the alternative --
    a truncated file a reader parses as broken JSON -- is worse.
    """
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = path + ".tmp"
    # Serialize to one text value and write it through an explicit utf-8 stream,
    # the way the rest of the bridge writes text (snapshot_store, ide_daemon_state).
    # A plain open() plus json.dump(ensure_ascii=False) is broken under
    # IronPython 2.7 for non-ASCII: the streaming path mixes str and unicode
    # chunks, so a Cyrillic object name or error message in the result made the
    # whole file fail to write -- and the one surviving record of an import the
    # CLI never received was lost. json.dumps returns bytes when the output is
    # all-ASCII and unicode otherwise, so decode the bytes before handing the
    # value to the text stream.
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if not isinstance(text, type(u"")):
        text = text.decode("utf-8")
    with io.open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.write(u"\n")
    try:
        os.replace(temporary, path)
    except AttributeError:
        if os.path.exists(path):
            os.remove(path)
        os.rename(temporary, path)
    return path


def result_path(sync_folder):
    """Where the last result for *sync_folder* lives, or ``None``."""
    if not sync_folder:
        return None
    return os.path.join(sync_folder, ".dump", RESULT_FILE_NAME)


def record_last_result(method, response, request_id=None, write_failed=False):
    """Persist *response* as the last result, if it is worth persisting.

    Returns the path written, or ``None`` when nothing was written -- an
    ordinary quick command whose response reached the caller. A write failure
    always records: the caller demonstrably did not get this answer.
    """
    if not write_failed and method not in ALWAYS_RECORD:
        return None

    sync_folder, error = _sync_folder()
    path = result_path(sync_folder)
    if path is None:
        _log(
            "Could not record last result for {0}: {1}".format(
                method, error or "sync folder unknown"
            )
        )
        return None

    data = response.get("data") if isinstance(response, dict) else None
    payload = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id or "",
        "method": method,
        "recorded_at": ide_time.iso_utc(),
        "delivered": not write_failed,
        "ok": bool(response.get("ok")) if isinstance(response, dict) else False,
        "error": (response.get("error") if isinstance(response, dict) else None) or "",
        "result": data if isinstance(data, dict) else {},
    }
    saved = data.get("saved") if isinstance(data, dict) else None
    if saved is not None:
        payload["saved"] = bool(saved)
    try:
        write_json_atomic(path, payload)
    except Exception as exc:
        _log("Could not write last result to {0}: {1}".format(path, exc))
        return None

    _log(
        "Recorded last result for {0}{1} (delivered={2}): {3}".format(
            method,
            " [{0}]".format(request_id) if request_id else "",
            payload["delivered"],
            path,
        )
    )
    return path


def refused_path(sync_folder):
    """Where the "an import was refused" marker lives, or ``None``."""
    if not sync_folder:
        return None
    return os.path.join(sync_folder, ".dump", IMPORT_REFUSED_FILE_NAME)


def record_import_refusal(reason, command="import"):
    """Remember that an import was refused, so a later build can say so.

    Best effort: a missing marker only costs a note, so a write failure is
    logged and swallowed rather than failing the refusal itself.
    """
    sync_folder, error = _sync_folder()
    path = refused_path(sync_folder)
    if path is None:
        _log("Could not record refused import: {0}".format(error or "no sync folder"))
        return None
    payload = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": ide_time.iso_utc(),
        "command": command,
        "reason": reason or "",
    }
    try:
        write_json_atomic(path, payload)
    except Exception as exc:
        _log("Could not write refused-import marker to {0}: {1}".format(path, exc))
        return None
    return path


def clear_import_refusal():
    """Drop the marker after a successful import."""
    sync_folder, _error = _sync_folder()
    path = refused_path(sync_folder)
    if path is None:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as exc:
        _log("Could not clear refused-import marker {0}: {1}".format(path, exc))


def read_import_refusal():
    """The refused-import marker as a dict, or ``None`` when there is none."""
    sync_folder, _error = _sync_folder()
    path = refused_path(sync_folder)
    if path is None or not os.path.isfile(path):
        return None
    try:
        with io.open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _cmd_last_result(params=None):
    """Read back the last recorded command result (``cts last-result``)."""
    sync_folder, error = _sync_folder()
    path = result_path(sync_folder)
    if path is None:
        return {
            "ok": False,
            "code": "no_sync_folder",
            "error": "Cannot resolve the sync folder: {0}".format(
                error or "unknown"
            ),
        }
    if not os.path.isfile(path):
        return {
            "ok": False,
            "code": "not_found",
            "error": (
                "No recorded command result at {0}. It is written when a sync "
                "command finishes, so there is nothing to show if none has "
                "run since the daemon started.".format(path)
            ),
            "path": path,
        }
    try:
        # utf-8-sig matches the writer and tolerates a BOM another tool left.
        with io.open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {
            "ok": False,
            "code": "unreadable",
            "error": "Could not read {0}: {1}".format(path, exc),
            "path": path,
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "code": "invalid",
            "error": "{0} does not contain a JSON object".format(path),
            "path": path,
        }
    payload["path"] = path
    return {"ok": True, "data": payload}

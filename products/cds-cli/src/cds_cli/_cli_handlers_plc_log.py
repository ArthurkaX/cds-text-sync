# -*- coding: utf-8 -*-
"""``cts plc-log`` -- read the PLC runtime log and extract ``CTS|`` events.

Thin wrapper over the daemon's ``plc_log`` method. The daemon can list the log
files, return a tail, or save the whole file; the CTS parsing (and the
``--level``/``--code`` filters) happens here on the CLI side, where Python is
cheap and testable, rather than in the IronPython 2.7 daemon.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

from cds_cli._cli_handlers_daemon import _daemon_timeout
from cds_cli._cli_io import (
    _format_output,
    _print_error,
    _print_rp_error,
    send_command_reverse,
)
from cds_cli.plc_log import filter_records, parse_cts_lines
from cts_shared import wire

DEFAULT_LOG_FILE = "codesyscontrol.log"


def _read_text(path):
    """Decode a downloaded log file, tolerating the runtime's encoding."""
    with open(path, "rb") as handle:
        content = handle.read()
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def dispatch_plc_log(args, output_fmt="json"):
    """Handle ``cts plc-log``. Return True if this was the command, else False."""
    if getattr(args, "command", None) != "plc-log":
        return False

    log_file = getattr(args, "file", "") or DEFAULT_LOG_FILE
    tail_n = int(getattr(args, "tail", 0) or 0)
    output_path = getattr(args, "log_output", "") or ""
    level = getattr(args, "level", "") or ""
    code = getattr(args, "code", "") or ""
    want_cts = bool(getattr(args, "cts", False) or level or code)

    params = {"file": log_file}
    if tail_n:
        params["tail"] = str(tail_n)
    if output_path:
        params["output"] = output_path

    # Parsing the whole log needs its text, but the daemon only returns a tail
    # (the full file can be tens of MB). With neither --tail nor --output the
    # CLI asks the daemon to save the log into a scratch folder, reads it
    # there, and deletes the folder again. This assumes the CLI and the daemon
    # share a filesystem -- true for a local CODESYS and for the SSH `cts-win`
    # wrapper, which runs the CLI inside the same VM.
    scratch_dir = None
    if want_cts and not output_path and not tail_n:
        scratch_dir = tempfile.mkdtemp(prefix="cts-plc-log-")
        params["output"] = scratch_dir

    try:
        timeout = _daemon_timeout("plc_log", getattr(args, "timeout", None), 60)
        try:
            response = send_command_reverse("plc_log", params, timeout=timeout)
        except RuntimeError as exc:
            _print_error("Reverse pipe error: {0}".format(exc))
            sys.exit(1)

        if not wire.response_ok(response):
            # Passes through the daemon's own message, e.g. "Not connected."
            _print_rp_error(response, "plc_log")
            sys.exit(1)

        data = response.get("data", {}) or {}

        if not want_cts:
            print(_format_output(data, fmt=output_fmt, title="plc-log"))
            return True

        lines, source = _cts_lines(data, tail_n, output_path)
        if lines is None:
            sys.exit(1)

        records = filter_records(parse_cts_lines(lines), level=level, code=code)
        payload = {
            "file": log_file,
            "source": source,
            "count": len(records),
            "parse_errors": sum(1 for r in records if r.get("parse_error")),
            "records": records,
        }
        if output_path and data.get("saved_to"):
            payload["saved_to"] = data["saved_to"]
        print(_format_output(payload, fmt=output_fmt, title="plc-log"))
        return True
    finally:
        if scratch_dir:
            shutil.rmtree(scratch_dir, ignore_errors=True)


def _cts_lines(data, tail_n, output_path):
    """Pick the lines to parse from a daemon response.

    Returns ``(lines, source)`` or ``(None, "")`` after reporting why no text
    could be read.
    """
    if tail_n:
        tail = data.get("tail")
        if not isinstance(tail, list):
            _print_error(
                "plc-log: daemon returned no tail ({0})".format(
                    data.get("tail_error") or "no tail in response"
                )
            )
            return None, ""
        return tail, "tail"

    saved_to = data.get("saved_to") or ""
    if not saved_to:
        reason = data.get("save_error") or (
            "daemon reported no saved file"
            if output_path
            else "the daemon did not save the log"
        )
        _print_error("plc-log: {0}".format(reason))
        return None, ""

    if not os.path.isfile(saved_to):
        _print_error(
            "plc-log: cannot read {0!r} on this host. If the CLI runs on a "
            "different machine than CODESYS, use --output DIR --cts and read "
            "the file there, or --tail N --cts.".format(saved_to)
        )
        return None, ""

    return _read_text(saved_to).splitlines(), "file"

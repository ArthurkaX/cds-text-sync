# -*- coding: utf-8 -*-
"""``cts new`` -- create a project-view object without the IDE.

Offline by design: the command edits the disk copy of the project, and the
existing ``compare``/``import``/``download`` steps carry the object into
CODESYS. Nothing here opens the pipe, so it works with no IDE running -- which
is the whole point, since a daemon call would need a project open and would buy
nothing.

The knowledge this replaces (the object's ST shape, its type GUID, and the fact
that a ``.st`` with a sibling ``.xml`` is discovered by neither of the reader's
pending-object passes) lives in ``cds_text_sync.engine.new_object``.
"""

from __future__ import annotations

import os
import sys

from cds_cli._cli_io import _format_output, _print_error


def dispatch_new_object(args, output_fmt="json"):
    """Handle ``cts new``. Return True if this was the command, else False."""
    if getattr(args, "command", None) != "new":
        return False

    from cds_text_sync.engine.new_object import NewObjectError, create_object

    try:
        report = create_object(
            _sync_folder(args),
            getattr(args, "new_kind", ""),
            getattr(args, "name", ""),
            parent=getattr(args, "parent", "") or "",
            text=getattr(args, "text", "") or "",
            text_file=getattr(args, "text_file", "") or "",
            pou_kind=getattr(args, "pou_kind", "") or "",
            dut_kind=getattr(args, "dut_kind", "") or "",
            return_type=getattr(args, "return_type", "") or "",
            base_type=getattr(args, "base_type", "") or "",
            language=getattr(args, "language", "") or "st",
        )
    except NewObjectError as exc:
        _print_error(exc.message)
        sys.exit(exc.exit_code)
    print(_format_output(report, fmt=output_fmt, title="new"))
    return True


#: How far up the tree to look for a project-view/ before giving up.
_MAX_ANCESTORS = 6


def _sync_folder(args):
    """The sync folder, resolved offline.

    ``--sync-folder`` wins (a ``project-view`` path resolves to its parent, as
    the other commands accept it). Otherwise walk up from the current directory
    looking for a ``project-view/``: asking the daemon would make an offline
    command need a running IDE, which is the one thing it must not do.
    """
    explicit = getattr(args, "sync_folder", "") or ""
    if explicit:
        base = os.path.abspath(explicit)
        if os.path.basename(os.path.normpath(base)) == "project-view" and os.path.isdir(
            base
        ):
            base = os.path.dirname(os.path.normpath(base))
        if not os.path.isdir(base):
            _print_error("No such folder: {0}".format(base))
            sys.exit(2)
        return base

    current = os.path.abspath(os.getcwd())
    for _ in range(_MAX_ANCESTORS):
        if os.path.isdir(os.path.join(current, "project-view")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    _print_error(
        "No project-view/ found here or in any parent folder. Pass "
        "--sync-folder <path> to point at the project."
    )
    sys.exit(2)


__all__ = ["dispatch_new_object"]

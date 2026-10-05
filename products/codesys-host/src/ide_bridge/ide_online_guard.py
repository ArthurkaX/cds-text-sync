# -*- coding: utf-8 -*-
"""ide_online_guard.py -- refuse project edits while the IDE is online.

The rule is the user's: a CODESYS project must not be edited while the IDE is
logged in to the PLC. The IDE is not built for it, and an import that slips
through while online leaves the new objects half-applied -- their symbols are
never exported to the running application, so every later read fails with
``is not exported to the online application`` even after a full download.

Every command that edits the project asks this module for a refusal first, and
one helper answers for all of them. A per-handler copy would drift, and the
check has to run before the handler touches the project, the manifest or any
file, so that a refused edit leaves nothing half-written. Each refusal is also
written to the daemon log beside "Adopted existing IDE online session", so the
IDE-side story of a failed edit is visible from the log alone.

IronPython 2.7: no f-strings, no annotations, no pathlib.
"""

from __future__ import print_function

import ide_online_helpers

from ide_daemon_state import _log

# The refusal text is fixed apart from the command name; tests pin the
# ``cts disconnect`` instruction so it cannot be reworded into a dead end.
_REFUSAL = (
    "The IDE is online with the PLC; editing the project while online is not "
    "supported. Run `cts disconnect`, then repeat {0}."
)

#: Daemon method -> the ``cts`` command a person would actually retype.
#: The refusal must name something the caller can type, and the method names
#: (``sync_import_text``, ``set_sync_folder``) are internal. A test walks the
#: handlers' call sites and fails when one is missing here, so a new guarded
#: command cannot silently keep the internal spelling.
CLI_COMMANDS = {
    "sync_import": "import",
    "sync_import_text": "import",
    "update_pou": "update-pou",
    "delete_pou": "delete-pou",
    "set_sync_folder": "set-sync-folder",
    "set_simulation_mode": "project simulate",
}


def cli_command(method):
    """The ``cts`` command to repeat after disconnect, for a daemon method."""
    return "`cts {0}`".format(CLI_COMMANDS.get(method, method))


def _live_session(project):
    """The session the IDE already holds -- cached or not -- else ``None``.

    ``live_online_session`` returns the daemon's cached handle and, when there
    is none, *adopts* the session already online in the IDE UI. Adopting only
    creates a wrapper around the session the user already has; it never calls
    ``login()`` and never opens a connection (see
    ``ide_online_helpers.live_online_session``). ``disconnect`` checks the
    same predicate, so "edits are allowed" and "the session is gone" agree.

    This is deliberately not ``is_online_session_active``: that one reads only
    the daemon's cache, so it answers "offline" whenever the daemon started
    before the user logged in -- exactly how an online import slipped through
    while the IDE was logged in. Caching a handle it already had is not a
    project modification (see command_registry.NO_PERMISSION).
    """
    try:
        return ide_online_helpers.live_online_session(project)
    except Exception:
        return None


def project_edit_refusal(project, command):
    """The refusal dict when the IDE is online and ``command`` would edit.

    Returns ``None`` when the edit may proceed. ``command`` is the daemon
    method name; the message names the CLI command it stands for, so the
    caller is told exactly what to repeat after ``cts disconnect``.
    """
    if _live_session(project) is None:
        return None
    _log("edit refused: IDE online ({0})".format(command))
    return {"ok": False, "error": _REFUSAL.format(cli_command(command))}


__all__ = ["project_edit_refusal", "cli_command", "CLI_COMMANDS"]

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
file, so that a refused edit leaves nothing half-written.

IronPython 2.7: no f-strings, no annotations, no pathlib.
"""

from __future__ import print_function

import ide_online_helpers

# The refusal text is fixed apart from the command name; tests pin the
# ``cts disconnect`` instruction so it cannot be reworded into a dead end.
_REFUSAL = (
    "The IDE is online with the PLC; editing the project while online is not "
    "supported. Run `cts disconnect`, then repeat {0}."
)


def _live_session(project):
    """The session the IDE already holds -- cached or not -- else ``None``.

    ``require_online_session`` returns the daemon's cached handle and, when
    there is none, *adopts* the session already online in the IDE UI. Adopting
    only creates a wrapper around the session the user already has; it never
    calls ``login()`` and never opens a connection (see
    ``ide_online_helpers.require_online_session``).

    This is deliberately not ``is_online_session_active``: that one reads only
    the daemon's cache, so it answers "offline" whenever the daemon started
    before the user logged in -- exactly how an online import slipped through
    while the IDE was logged in. Caching a handle it already had is not a
    project modification (see command_registry.NO_PERMISSION).
    """
    try:
        return ide_online_helpers.require_online_session(project)
    except Exception:
        return None


def project_edit_refusal(project, command):
    """The refusal dict when the IDE is online and ``command`` would edit.

    Returns ``None`` when the edit may proceed. ``command`` is the daemon
    method name, the same spelling the other daemon errors use, so the message
    tells the caller exactly what to repeat after ``cts disconnect``.
    """
    if _live_session(project) is None:
        return None
    return {"ok": False, "error": _REFUSAL.format(command)}


__all__ = ["project_edit_refusal"]

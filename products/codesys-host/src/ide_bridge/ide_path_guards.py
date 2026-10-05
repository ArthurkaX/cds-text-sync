# -*- coding: utf-8 -*-
"""Path guards the daemon applies to paths that cross the pipe.

Two rules, and they are opposite:

* A **host** path the daemon opens must be absolute.  This process runs inside
  CODESYS.exe, whose working directory is the IDE's installation directory, so
  a relative path silently lands next to the IDE (or dies with an
  UnauthorizedAccessException) instead of where the caller meant.  The CLI
  absolutises the host paths it sends -- see ``cds_cli._cli_io._daemon_path``
  -- and ``host_path_error`` is the daemon's own answer for any other client,
  so "path must be absolute" always comes from one place.

* A **PLC** path names a file on the device, not on this host.  It is never
  absolutised here, and the MSYS rewrite Git Bash applies to a leading ``/``
  before ``cts`` even sees the argument is refused with a hint rather than
  sent to the device (see ``plc_path_error``).

IronPython 2.7.
"""

from __future__ import print_function

import os

#: What a caller may pass to mean "the device's root directory".  Git Bash
#: rewrites a leading ``/`` into a Windows path, so the root cannot be spelled
#: ``/`` from that shell; ``.`` and "" are what survive.
PLC_ROOT_TOKENS = (".", "")


def as_text(value):
    """``value`` as text, ``""`` for ``None`` (IronPython has no ``str``/``unicode`` split)."""
    if value is None:
        return ""
    try:
        return unicode(value)  # noqa: F821 - IronPython
    except NameError:
        return str(value)


def host_path_error(params, *names):
    """An error dict if any named host file path is relative, else ``None``.

    Empty values are skipped: an unset option keeps an empty string so callers
    can omit the parameter, and that is not a relative path.
    """
    for name in names:
        value = as_text(params.get(name, ""))
        if value and not os.path.isabs(value):
            return {
                "ok": False,
                "error": "path must be absolute: {0} {1}".format(name, value),
            }
    return None


def _looks_like_msys_conversion(value):
    """True when a "PLC path" is really a host path Git Bash rewrote.

    MSYS turns an argument that starts with ``/`` into the path of that file
    under the Git installation (``/`` -> ``C:/Program Files/Git/``) before the
    program runs.  A device path is POSIX-style or relative, so an absolute
    Windows path (a drive letter, or a UNC share) in a PLC-path parameter is
    that rewrite -- not a file on the PLC.
    """
    if not value:
        return False
    if len(value) >= 2 and value[1] == ":" and value[0].isalpha():
        return True
    return value.startswith("\\\\") or value.startswith("//")


def plc_path_error(name, value):
    """An error dict when a PLC path looks like MSYS rewrote it, else ``None``."""
    text = as_text(value)
    if not _looks_like_msys_conversion(text):
        return None
    return {
        "ok": False,
        "error": (
            "PLC path in '{0}' looks like a path on this PC, not on the "
            "device: {1}. Git Bash rewrites an argument that starts with '/' "
            "into a Windows path before 'cts' sees it. For the PLC root pass "
            "'.', or run with MSYS_NO_PATHCONV=1 to keep a leading '/' as "
            "typed."
        ).format(name, text),
    }


def plc_root_path(value):
    """A PLC path with a root token (``.`` or "") normalised to the device root.

    The device API takes the root as an empty string; ``/`` cannot be used
    because Git Bash has already rewritten it by the time the daemon runs.
    """
    text = as_text(value)
    return "" if text in PLC_ROOT_TOKENS else text


__all__ = [
    "PLC_ROOT_TOKENS",
    "as_text",
    "host_path_error",
    "plc_path_error",
    "plc_root_path",
]

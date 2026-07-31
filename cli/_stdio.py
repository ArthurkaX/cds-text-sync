# -*- coding: utf-8 -*-
"""Shared stdio helpers.

Kept in its own tiny module so that lightweight commands (``cts install-menu``,
``cts where``) can force UTF-8 output without importing the offline engine.

Note: ``cli/external_engine/engine_cli.py`` carries its own copy of this shim.
It is executed as a bare script (``python <path>/engine_cli.py``) and imported
flat by the tests, so the ``cli`` package is not on ``sys.path`` at that point
and it cannot import this module. Keep the two bodies in step.
"""

import sys


def configure_stdio_utf8():
    """Force stdout/stderr to UTF-8 so diagnostic prints never crash.

    Windows consoles (and redirected pipes) default sys.stdout to the legacy
    ANSI codepage (cp1252), which raises UnicodeEncodeError the moment a line
    contains a non-cp1252 character -- e.g. a user profile folder named in
    Cyrillic, which is exactly what the install paths run through. That crash
    exits non-zero before any useful work. errors="replace" keeps us alive even
    on odd streams.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

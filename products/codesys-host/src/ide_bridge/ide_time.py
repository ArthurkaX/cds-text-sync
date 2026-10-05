# -*- coding: utf-8 -*-
"""ide_time.py -- one zone for every timestamp a daemon response carries.

Live, ``tree_built_at`` read ``09:44`` while the host clock said ``20:45``:
the daemon formatted a *local* time with no zone marker, so two clocks
disagreed about what the string meant. Every timestamp the daemon reports is
now ISO-8601 in UTC with a trailing ``Z`` -- ``2026-10-05T20:45:12Z`` -- so a
reader never has to guess the zone. Values written before the rule (no ``Z``)
are still read as they are; nothing parses them, and a missing zone is not an
error. Human-readable log prefixes stay in local time: they are read on the
daemon's own host, not compared across machines.

IronPython 2.7: no f-strings, no annotations.
"""

from __future__ import print_function

import time

#: The one format for response timestamps.
ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"


def iso_utc(epoch=None):
    """Now, or an epoch seconds value, as ISO-8601 UTC with a trailing Z."""
    stamp = time.gmtime() if epoch is None else time.gmtime(epoch)
    return time.strftime(ISO_UTC, stamp)


__all__ = ["iso_utc", "ISO_UTC"]

"""fsm_rules.py - FSM detection helpers (shared, IronPython-safe).

``normalize`` and ``same_family`` are the validated name-folding rules from
the FSM corpus. They are defined once here and imported by the detector and
the tests so the tests never re-type them.
"""

from __future__ import print_function

import re

_NEXT_NEW = re.compile(r"(?i)next|new")


def normalize(name):
    """Fold NEXT_STATE / P.next_state / _nextFsmState onto their base name."""
    stripped = _NEXT_NEW.sub("", name.upper())
    return re.sub(r"[^A-Z0-9]", "", stripped)


def _split_member(expr):
    expr = expr.strip()
    if "." in expr:
        prefix, member = expr.rsplit(".", 1)
        return prefix.upper(), member.upper()
    return "", expr.upper()


def same_family(lhs, head):
    """True when *lhs* is the selector itself or its next_/new_ twin.

    Splits both at the last ``.``; prefixes must match case-insensitively
    (``""`` prefix when there is no dot); then ``normalize(member)`` must be
    equal.
    """
    lp, lm = _split_member(lhs)
    hp, hm = _split_member(head)
    if lp != hp:
        return False
    return normalize(lm) == normalize(hm)

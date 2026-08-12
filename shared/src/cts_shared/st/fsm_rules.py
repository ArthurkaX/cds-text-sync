"""fsm_rules.py - FSM detection helpers (shared, IronPython-safe).

``normalize`` and ``same_family`` are the validated name-folding rules from
the FSM corpus. They are defined once here and imported by the detector and
the tests so the tests never re-type them.
"""

from __future__ import print_function

import re

_NEXT_NEW = re.compile(r"(?i)next|new")

_PHASE = re.compile(
    r"(?i)(?:^|(?<=[_.]))(?:current|actual|curr|akt|act|cur)(?=[_.]|[A-Z0-9]|$)"
    r"|_(?:current|actual|curr|akt|act|cur)$"
)


def normalize(name):
    """Fold NEXT_STATE / P.next_state / _nextFsmState onto their base name.

    Also folds the "current" half of an act/next pair, so a selector
    written ``p.act_step`` pairs with the ``p.next_step`` it is swapped
    with. The phase token is stripped only where the name shows a word
    boundary -- start of name, after an underscore, before an underscore
    or a capital -- so ``impact`` and ``reactor`` are left alone. An
    all-capital name carries no boundary, so ``CURSOR_POS`` does fold to
    ``SORPOS``; that only matters if another name folds onto it too. The
    boundary set also includes the ``.`` of a dotted member, so the whole
    expression ``p.act_step`` folds the same way the bare member does.
    """
    trimmed = _PHASE.sub("", name)
    stripped = _NEXT_NEW.sub("", trimmed.upper())
    folded = re.sub(r"[^A-Z0-9]", "", stripped)
    if folded:
        return folded
    # A name that is nothing but a phase token ("act") keeps its own
    # spelling rather than folding onto every other such name.
    return re.sub(r"[^A-Z0-9]", "", _NEXT_NEW.sub("", name.upper()))


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

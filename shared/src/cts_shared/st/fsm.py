"""fsm.py - Finite-state-machine extraction from Structured Text (shared).

Detects state machines implemented as a ``CASE`` over a state variable whose
branches assign to the same variable (or its ``next_``/``new_`` twin). The
detection rule is validated against a real corpus; do not redesign it.

``find_machines`` takes the RAW implementation section (unblanked). It blanks
internally, builds the block tree, and stores every offset as an offset into
the raw text plus ``base``.

This module is deliberately self-contained and runs on both CPython 3.11 and
IronPython 2.7 (no f-strings, no annotations, no dataclasses).
"""

from __future__ import print_function

import re

from .blanking import blanked
from .blocks import scan
from .statements import statements
from .fsm_rules import normalize, same_family

_HEAD = re.compile(r"^[A-Za-z_][\w.\[\]]*$")
_OF = re.compile(r"\bOF\b", re.IGNORECASE)
_ASSIGN_IN_STMT = re.compile(r"([A-Za-z_][\w.\[\]]*)\s*:=")
_NUMERIC_LABEL = re.compile(r"^(\d+|16#[0-9A-Fa-f]+)$")
_WS = re.compile(r"\s+")
# An IF arm's label is its header text, which starts at the keyword. Drop a
# leading "IF" so a guard reads as the boolean expression it is -- otherwise
# joining a nested arm yields "ELSIF a AND IF b". "ELSIF" and "ELSE" are kept:
# they say the arm is reached only when the earlier ones did not fire, which a
# reviewer needs in order to tell exclusive branches from parallel ones.
_LEADING_IF = re.compile(r"(?i)^IF\b\s*")


class Machine(object):
    """One CASE site that may or may not be a state machine."""

    def __init__(self, selector, selector_offset, case_start, case_end):
        self.selector = selector
        self.selector_offset = selector_offset
        self.case_start = case_start
        self.case_end = case_end
        self.states = []
        self.transitions = []
        self.commit_offset = None
        self.deferred = False
        self.numeric = False
        self.warnings = []
        self.is_fsm = False


class State(object):
    """One CASE branch (a state)."""

    def __init__(self, label, aliases, start_offset, end_offset, order):
        self.label = label
        self.aliases = aliases
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.order = order


class Transition(object):
    """One state-variable assignment that targets a known state."""

    def __init__(self, source, target, guard, offset, lhs, deferred):
        self.source = source
        self.target = target
        self.guard = guard
        self.offset = offset
        self.lhs = lhs
        self.deferred = deferred


def _iter_cases(node):
    if node.kind == "CASE":
        yield node
    for child in node.children:
        for case in _iter_cases(child):
            yield case


def _state_label_for_rhs(states, rhs):
    up = rhs.upper()
    for st in states:
        if any(alias.upper() == up for alias in st.aliases):
            return st.label
    return rhs


def _source_for_offset(state_branches, offset, case_start, case_end):
    if not (case_start <= offset < case_end):
        return None
    for label, start, end in state_branches:
        if start <= offset < (end or offset + 1):
            return label
    return None


def _innermost_containing(node, offset):
    for child in node.children:
        if child.start_offset <= offset < (child.end_offset or offset + 1):
            return _innermost_containing(child, offset)
    return node


def _branch_label_containing(node, offset):
    for label, start, end in node.branches:
        if start <= offset < (end or offset + 1):
            return label
    return None


def _guard_for(root, case, offset):
    """Collect the enclosing IF-branch labels for a transition at *offset*.

    Walks up from the innermost block containing *offset*, collecting the
    label of the enclosing IF-branch at each level, skipping CASE nodes, and
    stopping at the state's own CASE (for a source transition) or the root
    (for a global transition). Joined outermost-first with `` AND ``.
    """
    node = _innermost_containing(root, offset)
    labels = []
    while node is not None and node is not root:
        if node.kind == "IF":
            label = _branch_label_containing(node, offset)
            if label is not None:
                labels.append(_LEADING_IF.sub("", label.strip()))
        if node is case:
            break
        node = node.parent
    labels.reverse()
    guard = " AND ".join(labels)
    return _WS.sub(" ", guard).strip()


def _build_machine(text, work, root, case, base):
    local_cs = case.start_offset - base
    kw_end = local_cs + len("CASE")
    of_match = _OF.search(work, kw_end)
    if not of_match:
        return None
    of_local = of_match.start()
    head = text[kw_end:of_local].strip()
    if not _HEAD.match(head):
        return None
    case_start = of_local + len("OF") + base
    case_end = (
        case.end_offset - len("END_CASE")
        if case.end_offset is not None
        else case.end_offset
    )

    machine = Machine(head, case.start_offset + len("CASE"), case_start, case_end)

    # States from the CASE branches (ELSE is not a state).
    order = 0
    labelset = set()
    state_branches = []
    for label, start, end in case.branches:
        if label.upper() == "ELSE":
            continue
        aliases = [part.strip() for part in label.split(",") if part.strip()]
        machine.states.append(State(label, aliases, start, end, order))
        order += 1
        state_branches.append((label, start, end))
        for alias in aliases:
            labelset.add(alias.upper())

    machine.numeric = bool(machine.states) and all(
        _NUMERIC_LABEL.match(label) for label, _s, _e in state_branches
    )

    # Assignments, one statement at a time. Control-flow headers (CASE..OF,
    # labels, IF..THEN) are not semicolon-terminated, so a statement can span
    # several lines and hold several assignments; scan each statement for
    # ``lhs :=`` and skip named call arguments (``f(CMD := x)``) by checking
    # the character before the LHS.
    for abs_offset, stmt in statements(work, base=base):
        local = abs_offset - base
        for am in _ASSIGN_IN_STMT.finditer(stmt):
            lhs = am.group(1)
            lhs_local = local + am.start(1)
            # Skip named function-call arguments: the previous non-space char
            # before the LHS is "(" or ",".
            prev = lhs_local - 1
            while prev >= 0 and work[prev] in " \t\n":
                prev -= 1
            if prev >= 0 and work[prev] in "(,":
                continue
            if not same_family(lhs, head):
                continue
            rhs_start = local + am.end()
            rhs_end = local + len(stmt)
            # Match on the blanked text: an inline comment between ":=" and
            # ";" (``:= ST.B (* go *);``) must not hide the label. The raw
            # slice is kept only for the human-readable warning.
            rhs = work[rhs_start:rhs_end].strip()
            rhs_raw = text[rhs_start:rhs_end].strip()
            if rhs.upper() in labelset:
                target = _state_label_for_rhs(machine.states, rhs)
                source = _source_for_offset(state_branches, lhs_local + base, case_start, case_end)
                deferred = lhs.upper() != head.upper()
                guard = _guard_for(root, case, lhs_local + base)
                machine.transitions.append(
                    Transition(source, target, guard, lhs_local + base, lhs, deferred)
                )
            elif normalize(rhs) == normalize(head) and same_family(rhs, head):
                if machine.commit_offset is None:
                    machine.commit_offset = lhs_local + base
            else:
                machine.warnings.append(
                    (
                        lhs_local + base,
                        "assigns {0} to the state variable but no branch handles it".format(rhs_raw),
                    )
                )

    machine.deferred = any(t.deferred for t in machine.transitions)
    machine.is_fsm = len(machine.transitions) > 0

    if not machine.is_fsm:
        # A dispatch or lookup CASE is not a state machine. Reachability
        # diagnostics are meaningless there -- every branch trivially "has no
        # outgoing transition" -- and emitting them buries the real findings
        # under one warning per branch.
        machine.warnings = []
        return machine

    for st in machine.states:
        if not any(t.source == st.label for t in machine.transitions):
            machine.warnings.append(
                (st.start_offset, "state {0} has no outgoing transition".format(st.label))
            )
    for st in machine.states:
        if st.order != 0 and not any(t.target == st.label for t in machine.transitions):
            machine.warnings.append(
                (st.start_offset, "state {0} is never entered".format(st.label))
            )

    return machine


def find_machines(text, base=0):
    """Return a list of :class:`Machine` for every CASE site in *text*.

    *text* is the RAW implementation section. Offsets on the returned models
    are offsets into *text* plus *base*.
    """
    work = blanked(text)
    root = scan(work, base=base)
    machines = []
    for case in _iter_cases(root):
        machine = _build_machine(text, work, root, case, base)
        if machine is not None:
            machines.append(machine)
    return machines

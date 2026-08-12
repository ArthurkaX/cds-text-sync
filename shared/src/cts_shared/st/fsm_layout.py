"""GRAFCET-styled (IEC 60848) layout for a CASE state machine.

This computes a GRAFCET-styled layout, not a strict grafcet: steps are
numbered boxes, the initial step is double-bordered, a transition is a bar
across the link with its receptivity beside it, flow runs top-to-bottom
without arrowheads. But a CASE block is an arbitrary directed graph, so edges
that do not join two consecutive steps are routed as directed links down the
right, priority (source-is-None) transitions are summarised in a compact "any"
block above the steps, one row per transition, each naming its target step by
number, rather than drawn as links across the diagram, and there is no
AND-divergence because exactly one state is ever active.

The module is pure: it imports nothing but the stdlib (and needs none of it).
It duck-types the model from cts_shared/st/fsm.py:

    Machine      -> .selector (str), .states (list of State),
                    .transitions (list of Transition)
    State        -> .label (str), .order (int)
    Transition   -> .source (str or None), .target (str), .guard (str, may be
                    ""), .offset (int)

`source is None` means a priority transition written OUTSIDE the CASE (e.g.
`IF stop THEN state := IDLE`), i.e. "from any state".

IronPython 2.7 compatible: no f-strings, no type hints, no annotations, no
dataclasses, no enum, no pathlib, no `yield from`.
"""

STEP_H = 34
STEP_MIN_W = 170
STEP_PAD = 18
NUM_W = 34
TOP_MARGIN = 24
BOTTOM_MARGIN = 28
LEFT_MARGIN = 24
SPINE_GAP = 58
BRANCH_ROW_H = 26
BRANCH_TOP = 16
BRANCH_BAR_X = 26
SPINE_BAR_UP = 26
BAR_HALF = 15
LANE_W = 24
LANE_CLEAR = 24
GUARD_GAP = 12
GUARD_CHARS = 40
TEXT_H = 15
SELF_W = 24
ANY_W = 96
ANY_MIN_H = 34
GLOBAL_ROW_H = 24
GLOBAL_PAD = 14
GLOBAL_STUB = 34
GLOBAL_BAR_X = 16
GLOBAL_BLOCK_GAP = 34
NOTE_GAP = 16
CHAR_W = 7
HIT_TOL = 6
ALWAYS = "=1"


def _estimate_width(text):
    """Fallback text width when no GDI+ measurement is available."""
    return len(text or "") * CHAR_W


def _int_measure(fn):
    """Text measurement is float in GDI+, but every coordinate here is an int."""
    def measured(text):
        return int(fn(text))
    return measured


def common_prefix(labels):
    """The dotted enum prefix shared by every label, including the trailing dot.

    Returns "" unless every label is dotted and they all share one prefix.
    """
    if not labels:
        return ""
    for label in labels:
        if "." not in label:
            return ""
    parts = set()
    for label in labels:
        parts.add(label.rsplit(".", 1)[0])
    if len(parts) == 1:
        value = next(iter(parts))
        if value:
            return value + "."
    return ""


def strip_prefix(label, prefix):
    if prefix and label.startswith(prefix):
        return label[len(prefix):]
    return label


def clip_guard(guard, limit=GUARD_CHARS):
    """The receptivity as drawn beside a transition bar."""
    collapsed = " ".join((guard or "").split())
    if not collapsed:
        return ALWAYS
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit - 3] + "..."


def initial_label(machine):
    """Best guess at the initial step.

    A state with no incoming transition is the initial step when there is
    exactly one such state; otherwise fall back to the first CASE branch.
    A self transition says nothing about entry order, so it does not count.
    A priority transition does count: a state entered only by an `IF stop`
    outside the CASE is a reaction state, not the initial step, and letting
    it look like a root would push the real first branch down the diagram.
    """
    labels = [s.label for s in machine.states]
    if not labels:
        return None
    incoming = dict((label, 0) for label in labels)
    for t in machine.transitions:
        if t.source == t.target:
            continue
        if t.target in incoming:
            incoming[t.target] += 1
    roots = [label for label in labels if incoming[label] == 0]
    if len(roots) == 1:
        return roots[0]
    return labels[0]


def order_steps(machine):
    """Vertical order of the steps: depth-first from the initial step.

    Following each state's outgoing transitions in source order turns the
    dominant path through the CASE into a straight vertical spine; anything
    unreachable is appended in source order so no state is dropped.
    """
    labels = [s.label for s in machine.states]
    if not labels:
        return []
    known = set(labels)
    outgoing = dict((label, []) for label in labels)
    for t in sorted(machine.transitions, key=lambda t: t.offset):
        if t.source is None:
            continue
        if t.source == t.target:
            continue
        if t.source not in known or t.target not in known:
            continue
        targets = outgoing[t.source]
        if t.target not in targets:
            targets.append(t.target)
    start = initial_label(machine)
    order = []
    seen = set()
    stack = [start]
    while stack:
        label = stack.pop()
        if label in seen:
            continue
        seen.add(label)
        order.append(label)
        for target in reversed(outgoing[label]):
            if target not in seen:
                stack.append(target)
    for label in labels:
        if label not in seen:
            order.append(label)
    return order


def _near_segment(px, py, a, b, tol):
    """True when (px,py) is within *tol* of the ORTHOGONAL segment a-b."""
    ax, ay = a
    bx, by = b
    if ax == bx:
        return abs(px - ax) <= tol and min(ay, by) - tol <= py <= max(ay, by) + tol
    if ay == by:
        return abs(py - ay) <= tol and min(ax, bx) - tol <= px <= max(ax, bx) + tol
    return False  # only orthogonal polylines are produced


def _assign_lanes(spans):
    """Greedy interval colouring: spans is a list of (y, y) pairs in either order; each is normalised
    first, because a link that jumps up the page arrives reversed.

    Returns a list of lane indexes in the SAME order as *spans*. The lowest
    free lane wins, so the topmost link hugs the steps.
    """
    spans = [(min(a, b), max(a, b)) for a, b in spans]
    order = sorted(range(len(spans)), key=lambda i: (spans[i][0], spans[i][1]))
    lane_end = []
    result = [0] * len(spans)
    for i in order:
        s, e = spans[i]
        placed = False
        for lane in range(len(lane_end)):
            if lane_end[lane] + 8 < s:
                result[i] = lane
                lane_end[lane] = e
                placed = True
                break
        if not placed:
            result[i] = len(lane_end)
            lane_end.append(e)
    return result


class Step(object):
    def __init__(self, number, label, full_label, x, y, w, h, initial,
                 priority=False):
        self.number = number
        self.label = label
        self.full_label = full_label
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.initial = initial
        self.priority = priority

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w // 2

    @property
    def cy(self):
        return self.y + self.h // 2

    def contains(self, x, y):
        return self.x <= x <= self.right and self.y <= y <= self.bottom


class Link(object):
    def __init__(self, kind, transition, points, bar, guard_text, guard_at,
                 guard_w, arrow, note_text="", note_at=None, note_w=0):
        self.kind = kind
        self.transition = transition
        self.points = points
        self.bar = bar
        self.guard_text = guard_text
        self.guard_at = guard_at
        self.guard_w = guard_w
        self.arrow = arrow
        self.note_text = note_text
        self.note_at = note_at
        self.note_w = note_w

    def near(self, x, y, tol=HIT_TOL):
        if len(self.points) >= 2:
            for a, b in zip(self.points, self.points[1:]):
                if _near_segment(x, y, a, b, tol):
                    return True
        if self.guard_at is not None:
            gx, gy = self.guard_at
            if gx <= x <= gx + self.guard_w and gy <= y <= gy + TEXT_H:
                return True
        if self.note_at is not None:
            nx, ny = self.note_at
            if nx <= x <= nx + self.note_w and ny <= y <= ny + TEXT_H:
                return True
        return False


class Layout(object):
    def __init__(self, steps, links, width, height, prefix, any_box, dropped):
        self.steps = steps
        self.links = links
        self.width = width
        self.height = height
        self.prefix = prefix
        self.any_box = any_box
        self.dropped = dropped

    @property
    def has_any(self):
        return self.any_box is not None

    def step_for(self, label):
        for step in self.steps:
            if step.full_label == label:
                return step
        return None

    def step_at(self, x, y):
        for step in self.steps:
            if step.contains(x, y):
                return step
        return None

    def link_at(self, x, y):
        for link in self.links:
            if link.near(x, y):
                return link
        return None


def build_layout(machine, measure=None, guard_measure=None):
    if measure is None:
        measure = _estimate_width
    if guard_measure is None:
        guard_measure = measure
    measure = _int_measure(measure)
    guard_measure = _int_measure(guard_measure)

    order = order_steps(machine)
    if not order:
        return Layout([], [], LEFT_MARGIN * 2, TOP_MARGIN + BOTTOM_MARGIN, "",
                      None, 0)

    prefix = common_prefix(order)
    row_of = dict((label, index) for index, label in enumerate(order))

    globals_ = []
    selfs = []
    graph = []
    dropped = 0
    for t in sorted(machine.transitions, key=lambda t: t.offset):
        if t.source is None and t.target in row_of:
            globals_.append(t)
        elif t.source == t.target and t.source in row_of:
            selfs.append(t)
        elif (t.source in row_of and t.target in row_of and t.source != t.target):
            graph.append(t)
        else:
            dropped += 1

    spine = {}
    branches = []
    for t in graph:
        s = row_of[t.source]
        d = row_of[t.target]
        if d == s + 1 and s not in spine:
            spine[s] = t
        else:
            branches.append(t)
    branches_by_row = {}
    for t in branches:
        branches_by_row.setdefault(row_of[t.source], []).append(t)

    step_w = STEP_MIN_W
    for index, label in enumerate(order):
        caption = strip_prefix(label, prefix)
        step_w = max(step_w, NUM_W + measure(caption) + STEP_PAD * 2)
    step_w = int(step_w)

    step_x = LEFT_MARGIN

    if globals_:
        any_x = LEFT_MARGIN
        any_y = TOP_MARGIN
        any_h = max(ANY_MIN_H, len(globals_) * GLOBAL_ROW_H + GLOBAL_PAD)
        any_box = (any_x, any_y, ANY_W, any_h)
        top = any_y + any_h + GLOBAL_BLOCK_GAP
    else:
        any_box = None
        top = TOP_MARGIN

    gaps = {}
    for row in range(len(order)):
        gaps[row] = SPINE_GAP + BRANCH_ROW_H * len(branches_by_row.get(row, []))
    y = [0] * len(order)
    y[0] = top
    for row in range(1, len(order)):
        y[row] = y[row - 1] + STEP_H + gaps[row - 1]

    priority_targets = set(t.target for t in globals_)

    steps = []
    for row, label in enumerate(order):
        steps.append(Step(number=row + 1,
                          label=strip_prefix(label, prefix),
                          full_label=label,
                          x=step_x,
                          y=y[row],
                          w=step_w,
                          h=STEP_H,
                          initial=(row == 0),
                          priority=(label in priority_targets)))

    links = []

    # SPINE
    for r in sorted(spine):
        t = spine[r]
        source = steps[r]
        target = steps[r + 1]
        x = source.cx
        points = [(x, source.bottom), (x, target.y)]
        bar_y = target.y - SPINE_BAR_UP
        bar = (x, bar_y, "h")
        text = clip_guard(t.guard)
        guard_at = (x + BAR_HALF + GUARD_GAP, bar_y - TEXT_H // 2)
        guard_w = guard_measure(text)
        links.append(Link("spine", t, points, bar, text, guard_at, guard_w,
                          None))

    # SELF
    for t in selfs:
        step = steps[row_of[t.source]]
        cy = step.cy
        x0 = step.right
        x1 = x0 + SELF_W
        points = [(x0, cy - 9), (x1, cy - 9), (x1, cy + 9), (x0, cy + 9)]
        bar = (x0 + SELF_W // 2, cy - 9, "v")
        text = clip_guard(t.guard)
        guard_at = (x1 + GUARD_GAP, cy - TEXT_H // 2)
        guard_w = guard_measure(text)
        arrow = (x0, cy + 9, "left")
        links.append(Link("self", t, points, bar, text, guard_at, guard_w,
                          arrow))

    # BRANCH
    if branches:
        branch_guards = []
        for t in branches:
            source_row = row_of[t.source]
            j = branches_by_row[source_row].index(t)
            source = steps[source_row]
            target = steps[row_of[t.target]]
            exit_y = source.bottom + BRANCH_TOP + j * BRANCH_ROW_H
            entry_y = target.cy
            bar = (source.cx + BRANCH_BAR_X, exit_y, "v")
            text = clip_guard(t.guard)
            guard_at = (source.cx + BRANCH_BAR_X + GUARD_GAP,
                        exit_y - TEXT_H // 2)
            guard_w = guard_measure(text)
            branch_guards.append((t, bar, text, guard_at, guard_w,
                                  (exit_y, entry_y)))

        lane_base = step_x + step_w + 30
        for t, bar, text, guard_at, guard_w, _ in branch_guards:
            lane_base = max(lane_base, guard_at[0] + guard_w + LANE_CLEAR)
        for link in links:
            if link.kind in ("spine", "self", "branch") and link.guard_at is not None:
                lane_base = max(lane_base,
                                link.guard_at[0] + link.guard_w + LANE_CLEAR)

        spans = [ys for _, _, _, _, _, ys in branch_guards]
        lanes = _assign_lanes(spans)

        for (t, bar, text, guard_at, guard_w, (exit_y, entry_y)), lane in zip(
                branch_guards, lanes):
            source_row = row_of[t.source]
            source = steps[source_row]
            target = steps[row_of[t.target]]
            lane_x = lane_base + lane * LANE_W
            points = [(source.cx, source.bottom),
                      (source.cx, exit_y),
                      (lane_x, exit_y),
                      (lane_x, entry_y),
                      (target.right, entry_y)]
            arrow = (target.right, entry_y, "left")
            links.append(Link("branch", t, points, bar, text, guard_at,
                              guard_w, arrow))

    # GLOBAL
    if globals_:
        rows_top = any_y + (any_h - len(globals_) * GLOBAL_ROW_H) // 2
        for k, t in enumerate(globals_):
            target = steps[row_of[t.target]]
            row_y = rows_top + k * GLOBAL_ROW_H + GLOBAL_ROW_H // 2
            x0 = any_x + ANY_W
            x1 = x0 + GLOBAL_STUB
            points = [(x0, row_y), (x1, row_y)]
            bar = (x0 + GLOBAL_BAR_X, row_y, "v")
            guard_text = clip_guard(t.guard)
            guard_w = guard_measure(guard_text)
            guard_at = (x1 + GUARD_GAP, row_y - TEXT_H // 2)
            note_text = "-> {0}  {1}".format(target.number, target.label)
            note_w = guard_measure(note_text)
            note_at = (guard_at[0] + guard_w + NOTE_GAP, row_y - TEXT_H // 2)
            arrow = None
            links.append(Link("global", t, points, bar, guard_text, guard_at,
                              guard_w, arrow, note_text=note_text,
                              note_at=note_at, note_w=note_w))

    width = step_x + step_w + 60
    height = 0
    if any_box is not None:
        width = max(width, any_box[0] + any_box[2])
        height = max(height, any_box[1] + any_box[3])
    for step in steps:
        height = max(height, step.bottom)
    for link in links:
        for px, py in link.points:
            width = max(width, px + 30)
            height = max(height, py)
        if link.guard_at is not None:
            gx, gy = link.guard_at
            width = max(width, gx + link.guard_w + 20)
            height = max(height, gy + TEXT_H)
        if link.note_at is not None:
            nx, ny = link.note_at
            width = max(width, nx + link.note_w + 20)
            height = max(height, ny + TEXT_H)
    height += BOTTOM_MARGIN

    return Layout(steps, links, int(width), int(height), prefix, any_box,
                  dropped)

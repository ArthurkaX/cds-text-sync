"""GRAFCET-styled (IEC 60848) layout for a CASE state machine.

This computes a GRAFCET-styled layout, not a strict grafcet: steps are
numbered boxes, the initial step is double-bordered, a transition is a bar
across the link with its receptivity beside it, flow runs top-to-bottom
without arrowheads. A CASE block is an arbitrary directed graph rather than
a sequence, so it is cut into chains, one per column: the dominant path is
the first column and each side sequence splits off into its own, starting at
the row it branches from. A choice between two branches is drawn as two
ordinary links leaving the same step, with no divergence bar - exactly one
state is ever active, so a horizontal bar would wrongly read as two branches
running at once. Branches that stand side by side on one row and fall into
the same step below them are drawn as an OR convergence instead: each keeps
its own bar and receptivity, they meet on a shared rail just above the step
and one stem enters it. A backward hop within a column is drawn as a real link
running down a lane in the gutter to its left; anything longer becomes a
connector - a hook that drops out of the step, turns right and comes back up
into an arrowhead naming its target - and the target step records who arrives
there. Priority (source-is-None) transitions form a
divergence under an "any" box above the steps: one stem down to a horizontal
rail, then one drop per transition into a chip that shows the block it lands
in.

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
BRANCH_ROW_H = 26
BRANCH_TOP = 16
BRANCH_BAR_X = 26
BAR_HALF = 15
LANE_W = 24
LANE_CLEAR = 24
GUARD_GAP = 12
GUARD_CHARS = 40
TEXT_H = 15
SELF_W = 24
ANY_W = 96
CHAR_W = 7
HIT_TOL = 6
ALWAYS = "=1"

ROW_GAP = 62          # step bottom -> next step top, fits a bar and two text lines
COL_GAP = 44          # gap between two columns of steps
BAR_UP = 30           # the bar sits this far above the step it leads into
FORK_DROP = 20        # a link drops this far before turning sideways
ANY_STEM = 22         # stem below the "any" box down to the rail
BRANCH_GAP = 44       # gap between two priority branches
JUMP_MAX_ROWS = 3     # a longer backward hop becomes a connector, not a line
JUMP_H = 30           # height of a connector's arrow + caption
JUMP_GAP = 10         # bar -> connector arrow
JUMP_W = 22           # the connector hook's horizontal run
INBOUND_W = 26        # left gutter for the "N -> " marker on a jump target
MERGE_RAIL = 20       # shared convergence rail, this far above the target


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


def build_chains(machine):
    """Cut the graph into vertical chains, one per column.

    A CASE block is not a sequence: it usually has one dominant path plus a
    few side sequences that split off it and rejoin later. Walking the first
    unvisited outgoing edge until it runs out gives one such chain; whatever
    is left starts the next one, placed one row below where it splits off.
    Reading the columns beats reading one tall column with links looping
    across it.
    """
    labels = [s.label for s in machine.states]
    if not labels:
        return []
    known = set(labels)
    outgoing = {}                       # label -> [target, ...] in source order, deduped
    for t in sorted(machine.transitions, key=lambda t: t.offset):
        if t.source is None:
            continue
        if t.source == t.target:
            continue
        if t.source not in known or t.target not in known:
            continue
        targets = outgoing.setdefault(t.source, [])
        if t.target not in targets:
            targets.append(t.target)
    visited = set()
    chains = []
    row_of = {}                         # label -> absolute row, filled as we go
    seeds = [(initial_label(machine), None)]      # (label, entry_label)
    while seeds:
        label, entry = seeds.pop(0)
        if label in visited:
            continue
        if entry is None:
            start_row = 0
        else:
            start_row = row_of[entry] + 1
        walk = []
        row = start_row
        cur = label
        while cur is not None and cur not in visited:
            visited.add(cur)
            row_of[cur] = row
            walk.append(cur)
            row += 1
            nxt = None
            for target in outgoing.get(cur, []):
                if target not in visited:
                    nxt = target
                    break
            cur = nxt
        chains.append({"labels": walk, "entry": entry, "entry_row": start_row})
        # every unvisited target of anything just walked seeds a new chain
        for source in walk:
            for target in outgoing.get(source, []):
                if target not in visited:
                    seeds.append((target, source))
    # anything unreachable gets its own chain at row 0, in source order
    for label in labels:
        if label not in visited:
            visited.add(label)
            row_of[label] = 0
            chains.append({"labels": [label], "entry": None, "entry_row": 0})
    return chains


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


class Chip(object):
    """A miniature step box: the target of a priority transition, drawn so
    the reader sees which block it lands in without hunting for it."""

    def __init__(self, number, label, x, y, w, h):
        self.number = number
        self.label = label
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def cy(self):
        return self.y + self.h // 2


class Step(object):
    def __init__(self, number, label, full_label, x, y, w, h, initial,
                 priority=False, col=0, row=0):
        self.number = number
        self.label = label
        self.full_label = full_label
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.initial = initial
        self.priority = priority
        self.col = col
        self.row = row
        self.inbound = []     # numbers of steps that reach this one by connector

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
    def __init__(self, steps, links, width, height, prefix, any_box, dropped,
                 chips=None, columns=1):
        self.steps = steps
        self.links = links
        self.width = width
        self.height = height
        self.prefix = prefix
        self.any_box = any_box
        self.dropped = dropped
        self.chips = chips or []
        self.columns = columns

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

    chains = build_chains(machine)
    if not chains:
        return Layout([], [], LEFT_MARGIN * 2, TOP_MARGIN + BOTTOM_MARGIN, "",
                      None, 0)

    order = []              # labels in reading order: column by column
    for chain in chains:
        order.extend(chain["labels"])
    prefix = common_prefix(order)
    number_of = dict((label, i + 1) for i, label in enumerate(order))
    col_of = {}
    row_of = {}
    for index, chain in enumerate(chains):
        for offset, label in enumerate(chain["labels"]):
            col_of[label] = index
            row_of[label] = chain["entry_row"] + offset

    # 6a. partition the transitions
    globals_ = []
    selfs = []
    graph = []
    dropped = 0
    for t in sorted(machine.transitions, key=lambda t: t.offset):
        if t.source is None and t.target in col_of:
            globals_.append(t)
        elif t.source == t.target and t.source in col_of:
            selfs.append(t)
        elif (t.source in col_of and t.target in col_of and t.source != t.target):
            graph.append(t)
        else:
            dropped += 1

    # 6b. classify the graph transitions
    chain_links = []
    forks = []
    sides = []
    jumps = []
    claimed = set()
    for t in graph:
        s_col = col_of[t.source]
        t_col = col_of[t.target]
        s_row = row_of[t.source]
        t_row = row_of[t.target]
        if (s_col == t_col and t_row == s_row + 1
                and (s_col, s_row) not in claimed):
            chain_links.append(t)
            claimed.add((s_col, s_row))
        elif (s_col != t_col and t_row == s_row + 1
              and t.target == chains[t_col]["labels"][0]):
            forks.append(t)
        elif s_col == t_col and abs(t_row - s_row) <= JUMP_MAX_ROWS:
            sides.append(t)
        else:
            jumps.append(t)

    # 6b'. convergence: several branches standing side by side on one row that
    # all fall into the same step below them. IEC 60848 draws that as an OR
    # convergence - every branch keeps its own receptivity, they meet on a
    # shared rail and one stem enters the step - so the group is pulled out of
    # the ordinary classes and laid out together. Without this the branch in
    # the target's own column reads as the sequence and the rest arrive as
    # unrelated connectors, hiding the fact that the routes rejoin.
    merges = []
    by_target = {}
    for t in graph:
        by_target.setdefault(t.target, []).append(t)
    for target_label in sorted(by_target.keys()):
        group = by_target[target_label]
        if len(group) < 2:
            continue
        rows = set(row_of[t.source] for t in group)
        cols = set(col_of[t.source] for t in group)
        # One row and one column each: anything else is not a side-by-side
        # divergence rejoining, and a rail drawn across it would cross boxes.
        if len(rows) != 1 or len(cols) != len(group):
            continue
        if row_of[target_label] != list(rows)[0] + 1:
            continue
        merges.extend(group)
    if merges:
        merged = set(id(t) for t in merges)
        chain_links = [t for t in chain_links if id(t) not in merged]
        forks = [t for t in forks if id(t) not in merged]
        sides = [t for t in sides if id(t) not in merged]
        jumps = [t for t in jumps if id(t) not in merged]
        merges.sort(key=lambda t: col_of[t.source])

    # 6c. step width and column x
    step_w = STEP_MIN_W
    for label in order:
        step_w = max(step_w, NUM_W + measure(strip_prefix(label, prefix)) + STEP_PAD * 2)
    step_w = int(step_w)

    # A side link runs down a lane in the gutter to the LEFT of its column:
    # the gutter to the right belongs to the next column's boxes.
    side_count = {}
    for t in sides:
        col = col_of[t.source]
        side_count[col] = side_count.get(col, 0) + 1
    gutter = {}
    for index in range(len(chains)):
        gutter[index] = INBOUND_W + LANE_W * side_count.get(index, 0)

    # Every receptivity is drawn to the right of its bar, so a column has to
    # be at least as wide as the longest one or the text lands on its neighbour.
    guard_room = 0
    for t in chain_links + forks + sides + jumps + merges:
        guard_room = max(guard_room, BAR_HALF + GUARD_GAP
                         + guard_measure(clip_guard(t.guard)))
    guard_room = int(guard_room)

    col_x = {}
    x = LEFT_MARGIN
    for index in range(len(chains)):
        x += gutter[index]
        col_x[index] = x
        x += step_w + guard_room + COL_GAP

    # 6d. the priority block, drawn as an ordinary GRAFCET divergence.
    # One stem drops out of the "any" box onto a single horizontal rail, and
    # every priority transition drops straight off that rail into its target.
    # It used to cascade down the stem and turn right into each target, which
    # reads as a chain of turns rather than as "any one of these can fire".
    links = []
    chips = []
    any_box = None
    if globals_:
        chip_w = STEP_MIN_W
        for t in globals_:
            chip_w = max(chip_w, NUM_W + measure(strip_prefix(t.target, prefix)) + STEP_PAD * 2)
        chip_w = int(chip_w)
        # A receptivity is drawn to the right of its own bar, so a branch has
        # to be wide enough for the longest one as well as for its chip.
        any_guard_room = 0
        for t in globals_:
            any_guard_room = max(any_guard_room, BAR_HALF + GUARD_GAP
                                 + guard_measure(clip_guard(t.guard)))
        branch_pitch = int(max(chip_w, chip_w // 2 + any_guard_room) + BRANCH_GAP)
        first_x = LEFT_MARGIN + INBOUND_W + chip_w // 2
        branch_x = [first_x + k * branch_pitch for k in range(len(globals_))]
        any_y = TOP_MARGIN
        rail_y = any_y + STEP_H + ANY_STEM
        bar_y = rail_y + FORK_DROP
        chip_y = bar_y + BAR_UP
        # The box sits over the middle of the rail, so the stem never doubles
        # back on itself and a lone priority transition draws as one drop.
        any_cx = (branch_x[0] + branch_x[-1]) // 2
        any_box = (any_cx - ANY_W // 2, any_y, ANY_W, STEP_H)
        for k, t in enumerate(globals_):
            x = branch_x[k]
            chip = Chip(number_of[t.target], strip_prefix(t.target, prefix),
                        x - chip_w // 2, chip_y, chip_w, STEP_H)
            chips.append(chip)
            text = clip_guard(t.guard)
            points = [(any_cx, any_y + STEP_H), (any_cx, rail_y),
                      (x, rail_y), (x, chip.y)]
            bar = (x, bar_y, "h")
            guard_at = (x + BAR_HALF + GUARD_GAP, bar_y - TEXT_H // 2)
            arrow = (x, chip.y, "down")
            links.append(Link("global", t, points, bar, text, guard_at,
                              guard_measure(text), arrow))
        top = max(chip.bottom for chip in chips) + ROW_GAP
    else:
        top = TOP_MARGIN

    # 6e. the steps
    row_y = {}   # absolute row -> y
    max_row = max(row_of.values())
    for r in range(max_row + 1):
        row_y[r] = top + r * (STEP_H + ROW_GAP)
    priority_targets = set(t.target for t in globals_)
    steps = []
    step_of = {}
    for label in order:
        step = Step(number=number_of[label],
                    label=strip_prefix(label, prefix),
                    full_label=label,
                    x=col_x[col_of[label]],
                    y=row_y[row_of[label]],
                    w=step_w, h=STEP_H,
                    initial=(label == order[0]),
                    priority=(label in priority_targets),
                    col=col_of[label], row=row_of[label])
        steps.append(step)
        step_of[label] = step

    # 6f. chain links: a straight vertical run with the bar above the target
    for t in chain_links:
        source = step_of[t.source]
        target = step_of[t.target]
        x = source.cx
        points = [(x, source.bottom), (x, target.y)]
        bar_y = target.y - BAR_UP
        bar = (x, bar_y, "h")
        text = clip_guard(t.guard)
        guard_at = (x + BAR_HALF + GUARD_GAP, bar_y - TEXT_H // 2)
        links.append(Link("chain", t, points, bar, text, guard_at,
                          guard_measure(text), None))

    # 6g. fork links: drop, turn sideways, drop into the other column
    # There is NO divergence bar: exactly one state is active, so a selection is
    # just two ordinary links leaving the same step.
    for t in forks:
        source = step_of[t.source]
        target = step_of[t.target]
        drop_y = source.bottom + FORK_DROP
        bar_y = target.y - BAR_UP
        points = [(source.cx, source.bottom), (source.cx, drop_y),
                  (target.cx, drop_y), (target.cx, target.y)]
        bar = (target.cx, bar_y, "h")
        text = clip_guard(t.guard)
        guard_at = (target.cx + BAR_HALF + GUARD_GAP, bar_y - TEXT_H // 2)
        links.append(Link("fork", t, points, bar, text, guard_at,
                          guard_measure(text), None))

    # 6h. self links
    for t in selfs:
        step = step_of[t.source]
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

    # 6i. side links: the existing lane logic, restricted to one column
    if sides:
        sides_by_source = {}
        for t in sides:
            sides_by_source.setdefault(t.source, []).append(t)
        for col in range(len(chains)):
            col_sides = [t for t in sides if col_of[t.source] == col]
            if not col_sides:
                continue
            side_guards = []
            for t in col_sides:
                source = step_of[t.source]
                target = step_of[t.target]
                j = sides_by_source[t.source].index(t)
                exit_y = source.bottom + BRANCH_TOP + j * BRANCH_ROW_H
                entry_y = target.cy
                bar = (source.cx - BRANCH_BAR_X, exit_y, "v")
                text = clip_guard(t.guard)
                guard_at = (source.right + GUARD_GAP, exit_y - TEXT_H // 2)
                guard_w = guard_measure(text)
                side_guards.append((t, source, target, bar, text, guard_at,
                                    guard_w, (exit_y, entry_y)))

            spans = [ys for _, _, _, _, _, _, _, ys in side_guards]
            lanes = _assign_lanes(spans)

            for (t, source, target, bar, text, guard_at, guard_w,
                 (exit_y, entry_y)), lane in zip(side_guards, lanes):
                lane_base = col_x[source.col] - LANE_CLEAR
                lane_x = lane_base - lane * LANE_W
                points = [(source.cx, source.bottom),
                          (source.cx, exit_y),
                          (lane_x, exit_y),
                          (lane_x, entry_y),
                          (target.x, entry_y)]
                arrow = (target.x, entry_y, "right")
                links.append(Link("side", t, points, bar, text, guard_at,
                                  guard_w, arrow))

    # 6j. jump connectors, drawn as the "external link" glyph: down out of the
    # step, right, then back up into an arrowhead, with the target named
    # beside the tip. The hook is the same whether the target sits above or
    # below on the page: a connector is a named hand-off, not a direction, and
    # two mirrored glyphs would leave the reader weighing the geometry against
    # the caption. The whole hook stays inside the old stub's footprint, so a
    # connector still never reaches across the page to the block it names.
    for t in jumps:
        source = step_of[t.source]
        target = step_of[t.target]
        x = source.cx
        bar_y = source.bottom + FORK_DROP
        tip_y = bar_y + JUMP_GAP
        foot_y = tip_y + JUMP_H
        hook_x = x + JUMP_W
        points = [(x, source.bottom), (x, foot_y),
                  (hook_x, foot_y), (hook_x, tip_y)]
        bar = (x, bar_y, "h")
        text = clip_guard(t.guard)
        guard_at = (x + BAR_HALF + GUARD_GAP, bar_y - TEXT_H // 2)
        arrow = (hook_x, tip_y, "up")
        note_text = "{0}  {1}".format(target.number, target.label)
        # Below the tip rather than level with it: level would collide with
        # the receptivity, which is drawn to the right of the bar just above.
        note_at = (hook_x + 10, tip_y + 2)
        links.append(Link("jump", t, points, bar, text, guard_at,
                          guard_measure(text), arrow,
                          note_text=note_text, note_at=note_at,
                          note_w=guard_measure(note_text)))
        target.inbound.append(source.number)

    # 6k. merge links: the OR convergence. Each branch drops out of its step
    # through its own bar and receptivity onto one shared rail just above the
    # target, and a single stem carries them into it. The branch already in
    # the target's column draws the same way; its rail run is zero-length, so
    # the three paths still read as one arrival rather than as a special case.
    for t in merges:
        source = step_of[t.source]
        target = step_of[t.target]
        rail_y = target.y - MERGE_RAIL
        bar_y = source.bottom + FORK_DROP
        points = [(source.cx, source.bottom), (source.cx, rail_y),
                  (target.cx, rail_y), (target.cx, target.y)]
        bar = (source.cx, bar_y, "h")
        text = clip_guard(t.guard)
        guard_at = (source.cx + BAR_HALF + GUARD_GAP, bar_y - TEXT_H // 2)
        links.append(Link("merge", t, points, bar, text, guard_at,
                          guard_measure(text), None))

    # 6l. extent
    width = LEFT_MARGIN + INBOUND_W + step_w + 60
    height = 0
    if any_box is not None:
        width = max(width, any_box[0] + any_box[2])
        height = max(height, any_box[1] + any_box[3])
    for chip in chips:
        width = max(width, chip.right)
        height = max(height, chip.bottom)
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
                  dropped, chips=chips, columns=len(chains))

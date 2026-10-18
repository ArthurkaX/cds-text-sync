---
title: Commented-out code
since: 3.0.0
related: [CTS0002]
---

## What it is

A comment whose content still looks like executable ST: an assignment
(`:=`), a call (`name(...)`), or a control-flow keyword (`IF`, `FOR`,
`WHILE`, `CASE`, `RETURN`, `EXIT`, ...).

## Why it is dangerous

Commented-out code is a second, unmaintained copy of the logic. It rots
silently, and the next reader cannot tell whether the comment is an old
alternative, a fix-in-progress, or a hint that the surrounding code is dead.
When the live code is later "fixed" to match the comment, the project ships
whatever the author re-enabled by feel. If the code is not needed, delete it:
git has the history.

## Example

```st bad 2
PROGRAM Main
VAR
    x : INT;
END_VAR

IMPLEMENTATION

x := 10;
// x := x + 5;  // cts:here
(* x := x * 2; *)  // cts:here
```

```st good
PROGRAM Main
VAR
    x : INT;
END_VAR

IMPLEMENTATION

// Increment is intentionally disabled this shift; see TICKET-482.
x := 10;
```

A comment of three lines or more is code when at least a third of its lines
read as code; prose that quotes a statement or two is documentation:

```st good
(*
Counts the cycles since the start.
A restart sets the counter back (the variables are initialised);
the host reads it as GVL_Bench.nCycles := nCycles + 1 would show.
Nothing else writes it.
*)
PROGRAM Main
VAR
    nCycles : DINT;
END_VAR
IMPLEMENTATION
nCycles := nCycles + 1;
```

```st bad 1
PROGRAM Main
VAR
    x : INT;
END_VAR
IMPLEMENTATION
(* old ramp, kept for reference // cts:here
IF x > 10 THEN
    x := 10;
END_IF;
*)
x := x + 1;
```

## When ignoring is legitimate

- The comment explains *why* the code is absent (`// disabled for TICKET-482`).
- The commented block is a documentation example, not real logic.
- A comment labels a formula or pseudocode example; prose such as
  `BOOL := TRUE` without a complete statement is not treated as code.
- The comment predates the git history and the team deliberately keeps it
  (prefer git history; this is usually a migration task, not a permanent
  exception).

## How to fix

Delete the commented block. If the logic is needed later, git can restore it;
if it is needed now, uncomment it as a deliberate change with a reason.

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

## When ignoring is legitimate

- The comment explains *why* the code is absent (`// disabled for TICKET-482`).
- The commented block is a documentation example, not real logic.
- The comment predates the git history and the team deliberately keeps it
  (prefer git history; this is usually a migration task, not a permanent
  exception).

## How to fix

Delete the commented block. If the logic is needed later, git can restore it;
if it is needed now, uncomment it as a deliberate change with a reason.

---
title: Identical control-flow branch bodies
---

## What it is

Reports two non-empty branches of the same `IF` or `CASE` block that contain
the same executable body after comments and formatting differences are
ignored.

## Why it is dangerous

Identical branches are often a copy-paste mistake, a condition that no longer
matters, or a missing operation in one branch. They make the control flow
harder to review and can hide a real distinction that was intended by the
author.

## Example

```st bad 1
IF State = Idle THEN
    StartMotor();
ELSIF State = Ready THEN // cts:here
    StartMotor();
END_IF;
```

```st good
IF State = Idle THEN
    StartMotor();
ELSIF State = Ready THEN
    PrepareMotor();
END_IF;
```

## When ignoring is legitimate

- Multiple labels intentionally perform the same safety action.
- The repeated body is temporary scaffolding with an issue or design note.

## How to fix

Verify the conditions and either remove the redundant branch, merge the
conditions, or restore the operation that should distinguish the branches.
No automatic rewrite is offered because the intended logic cannot be inferred
reliably.

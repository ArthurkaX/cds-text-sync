---
title: REPEAT condition not changed
since: 3.0.0
related: [CTS0017]
---

## What it is

A `REPEAT ... UNTIL` loop tests a variable that is never directly assigned in
the loop body.

This conservative check handles simple variable conditions and direct
assignments. Complex expressions, indirect updates through calls, and
qualified members are left for a future data-flow analysis.

## Why it is dangerous

The condition can remain false forever, causing the cyclic task to consume the
available scan time and eventually trip the watchdog.

## Example

```st bad 1
REPEAT
    Work();
UNTIL ready // cts:here
END_REPEAT;
```

```st good
REPEAT
    Work();
    ready := TRUE;
UNTIL ready
END_REPEAT;
```

## When ignoring is legitimate

- A called routine updates the condition variable indirectly.
- An external event changes the variable while the loop is running.
- The loop contains a deliberate alternate exit such as `EXIT`.

## How to fix

Update the condition variable explicitly in the loop body, or use a clear
alternate exit and document why the loop is bounded. For indirect updates,
make the data flow visible or suppress the finding with a reason.

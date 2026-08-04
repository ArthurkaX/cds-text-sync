---
title: Temporary function-block instance
---

## What it is

Reports a function-block instance declared locally in a function or method.
The type must match a `FUNCTION_BLOCK` present in the project.

## Why it is dangerous

Local instances are recreated when the enclosing function or method is called.
Their timers, edge detectors, counters, and other internal state do not survive
until the next call.

## Example

```st bad 1
// cts:fb TON
FUNCTION Calculate : BOOL
VAR
    Timer : TON; // cts:here
END_VAR
IMPLEMENTATION
Timer(IN := TRUE, PT := T#1s);
Calculate := Timer.Q;
```

```st good
FUNCTION_BLOCK Controller
VAR
    Timer : TON;
END_VAR
END_FUNCTION_BLOCK
```

## When ignoring is legitimate

- The function block is intentionally stateless for this particular call.
- Resetting the instance on every call is part of the algorithm.

## How to fix

Move the instance to persistent state owned by the calling program or function
block, and pass its inputs or expose its result through a clear interface.

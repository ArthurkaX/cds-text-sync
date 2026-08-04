---
title: Output not assigned on all paths
since: 3.0.0
related: [CTS0009]
---

## What it is

A `VAR_OUTPUT` of a `FUNCTION` or `METHOD` is assigned in a conditional branch
but not on every branch. `FUNCTION_BLOCK` outputs are excluded because they
commonly retain their previous value between cycles.

## Why it is dangerous

Callers can observe an undefined value when the condition is false.

## Example

```st bad 1
FUNCTION F : BOOL
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
IF Ready THEN
    Done := TRUE; // cts:here
END_IF;
```

```st good
FUNCTION F : BOOL
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
IF Ready THEN
    Done := TRUE;
ELSE
    Done := FALSE;
END_IF;
```

## When ignoring is legitimate

- Retaining the previous output value is an explicit interface contract.
- A surrounding generated wrapper guarantees a default before the callable.

## How to fix

Assign a default before the conditional or assign the output in every branch.

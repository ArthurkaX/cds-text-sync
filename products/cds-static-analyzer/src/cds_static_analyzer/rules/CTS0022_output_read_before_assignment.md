---
title: Output read before assignment
since: 3.0.0
related: [CTS0018, CTS0019]
---

## What it is

A `VAR_OUTPUT` of a function or method is read before that callable assigns
it. Function blocks are excluded because their outputs can intentionally retain
state between cycles.

## Why it is dangerous

The caller can observe an old or undefined value instead of a value produced by
the current call.

## Example

```st bad 1
FUNCTION F : BOOL
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
IF Done THEN // cts:here
    F := TRUE;
END_IF;
Done := TRUE;
```

```st good
FUNCTION F : BOOL
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
Done := FALSE;
IF Ready THEN
    Done := TRUE;
END_IF;
F := Done;
```

## When ignoring is legitimate

- The output is deliberately used as a retained value by a compatibility API.
- A generated wrapper initializes the output before entering the callable.

## How to fix

Assign a default to the output before reading it, or use a local variable for
the intermediate state.

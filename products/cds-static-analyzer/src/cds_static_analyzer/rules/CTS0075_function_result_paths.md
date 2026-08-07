---
title: Function result not assigned on all paths
since: 3.1.0
related: [CTS0009, CTS0019]
---

## What it is

A `FUNCTION` assigns its result variable only in some branches, or never
assigns it at all. The result variable has the same name as the function.

## Why it is dangerous

Callers receive an undefined, stale, or default value on the path without an
assignment. The error is often hidden because the successful path appears to
work during a quick test.

## Example

```st bad 1
FUNCTION GetValue : INT
VAR_INPUT
    ok : BOOL;
END_VAR
IMPLEMENTATION
IF ok THEN
    GetValue := 42; // cts:here
END_IF;
```

```st good
FUNCTION GetValue : INT
VAR_INPUT
    ok : BOOL;
END_VAR
IMPLEMENTATION
GetValue := 0;
IF ok THEN
    GetValue := 42;
END_IF;
```

## When ignoring is legitimate

- Every path that reaches the caller assigns the result through a project- or
  vendor-specific mechanism not visible in the source projection.
- The function is deliberately used only for side effects and its return value
  is not part of the contract; in that case use a procedure-style POU instead.

## How to fix

Assign a safe default at the start of the function, or add assignments to all
conditional and `CASE` branches. Make the default explicit rather than relying
on controller-specific initialization behavior.

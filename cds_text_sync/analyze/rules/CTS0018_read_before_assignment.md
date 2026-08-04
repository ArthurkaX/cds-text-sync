---
title: Read before assignment
since: 3.0.0
related: [CTS0011, CTS0012]
---

## What it is

A local variable is read before its first assignment in the analyzed
implementation.

## Why it is dangerous

The value may be undefined, stale, or dependent on runtime behavior. The bug
can be intermittent when the variable is stored across calls.

## Example

```st bad 1
FUNCTION Main : INT
VAR
    temp : INT;
END_VAR
IMPLEMENTATION
Main := temp + 1; // cts:here
```

```st good
FUNCTION Main : INT
VAR
    temp : INT;
END_VAR
IMPLEMENTATION
temp := 0;
Main := temp + 1;
```

## When ignoring is legitimate

- An external runtime contract initializes the storage before this code runs.
- The declaration has an explicit initial value.

## How to fix

Assign a defined value before the first read or declare an explicit initial
value where that is the intended lifetime behavior.

---
title: Overlapping CASE range
since: 3.0.0
related: [CTS0015]
---

## What it is

A `CASE` statement contains decimal labels or ranges whose values overlap an
earlier branch.

## Why it is dangerous

Only the first matching branch can execute. The overlapping part of the later
branch is unreachable, which can hide a missing transition or a copy-and-paste
error.

## Example

```st bad 1
PROGRAM Main
VAR
    state : INT;
END_VAR
IMPLEMENTATION
CASE state OF
    1..5: Start();
    5..10: Retry(); // cts:here
END_CASE;
```

```st good
PROGRAM Main
VAR
    state : INT;
END_VAR
IMPLEMENTATION
CASE state OF
    1..5: Start();
    6..10: Retry();
END_CASE;
```

## When ignoring is legitimate

- The labels are symbolic and their values are resolved by the compiler.
- A generated source file intentionally contains overlapping compatibility
  branches.

## How to fix

Make the ranges disjoint, or combine labels that intentionally share the same
behavior into one branch.

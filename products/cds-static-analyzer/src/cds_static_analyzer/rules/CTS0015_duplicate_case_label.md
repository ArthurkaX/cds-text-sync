---
title: Duplicate CASE label
since: 3.0.0
related: [CTS0003]
---

## What it is

A `CASE` statement contains the same label more than once.

## Why it is dangerous

Only the first matching branch can execute. The later branch is unreachable,
which can hide a missing transition or a copy-and-paste error.

## Example

```st bad 1
PROGRAM Main
VAR
    state : INT;
END_VAR
IMPLEMENTATION
CASE state OF
    1: Start();
    1: Retry();  // cts:here
END_CASE;
```

```st good
PROGRAM Main
VAR
    state : INT;
END_VAR
IMPLEMENTATION
CASE state OF
    1: Start();
    2: Retry();
END_CASE;
```

## When ignoring is legitimate

- The repeated text is separated into different nested `CASE` statements.
- A generated source file intentionally contains unreachable compatibility
  branches.

## How to fix

Remove the unreachable branch or give it a distinct label. If two labels need
the same behavior, combine them in one comma-separated label list.

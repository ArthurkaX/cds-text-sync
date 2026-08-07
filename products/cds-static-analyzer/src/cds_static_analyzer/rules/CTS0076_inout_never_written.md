---
title: VAR_IN_OUT never written
since: 3.1.0
related: [CTS0020, CTS0073]
---

## What it is

A `VAR_IN_OUT` parameter is read but never written by its POU. A parameter
with that contract is normally better represented as `VAR_INPUT`.

## Why it is dangerous

`VAR_IN_OUT` tells callers that the POU may modify their storage. Keeping that
stronger aliasing contract when no write occurs makes interfaces harder to
understand and can hide unnecessary coupling between POUs.

## Example

```st bad 1
FUNCTION IsReady : BOOL
VAR_IN_OUT
    ioState : INT; // cts:here
END_VAR
IMPLEMENTATION
IsReady := ioState > 0;
```

```st good
FUNCTION IsReady : BOOL
VAR_INPUT
    state : INT;
END_VAR
IMPLEMENTATION
IsReady := state > 0;
```

## When ignoring is legitimate

- The parameter is part of a stable public interface and must retain its
  `VAR_IN_OUT` contract for compatibility.
- A write happens through a library call or generated code whose formal
  parameter directions are unavailable to the analyzer.

## How to fix

Change the declaration to `VAR_INPUT` when the value is read-only. If the POU
is intended to update the caller's storage, add the missing assignment or
make that mutation explicit in the implementation.

---
title: PERSISTENT order changed
tags: [persistence, download, history]
since: 3.0.0
related: []
---

## What it is

A `VAR_GLOBAL PERSISTENT` block whose member order differs from the order at
the configured git base (default `HEAD`). Members are matched by name;
renames are out of scope (they appear as remove + add).

## Why it is dangerous

CODESYS persistent variables are mapped by position in the persistent
storage. Moving a member changes the address of every member after it: after
a download, a value that used to belong to `p_nTotal` can be read as
`p_rFactor`, silently corrupting process data. Reordering a PERSISTENT block
on a running plant is not a refactor, it is a migration.

## Example

```st bad
VAR_GLOBAL PERSISTENT RETAIN
    p_nShift : INT := 1;     (* moved: was last *)
    p_nTotal : INT := 0;
    p_bCalibrated : BOOL := FALSE;
    p_rFactor : REAL := 1.0;
END_VAR
```

```st good
VAR_GLOBAL PERSISTENT RETAIN
    p_nTotal : INT := 0;
    p_bCalibrated : BOOL := FALSE;
    p_rFactor : REAL := 1.0;
    p_nShift : INT := 1;
END_VAR
```

## When ignoring is legitimate

- The project has never been downloaded with persistent data (greenfield).
- The base commit predates the introduction of persistence and the order was
  never live.
- The change is a deliberate migration with a documented data-shift plan.

## How to fix

Append new persistent variables at the end of the block. If an order change
is unavoidable, treat it as a migration: document the address shift, plan the
download, and reset/migrate the persistent data.

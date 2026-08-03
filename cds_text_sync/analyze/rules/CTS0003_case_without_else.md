---
title: CASE without ELSE
since: 3.0.0
related: [CTS0001]
---

## What it is

A `CASE ... OF` statement without an `ELSE` branch. The `ELSE` branch is the
explicit decision for values that are not listed in the current cases.

## Why it is dangerous

When a new state or an unexpected value reaches the `CASE`, the program can
silently do nothing. Requiring `ELSE` makes the programmer decide whether to
report, reject, recover from, or deliberately ignore that value.

## Example

```st bad 1
CASE state OF  // cts:here
    1: Start();
    2: Stop();
END_CASE;
```

```st good
CASE state OF
    1: Start();
    2: Stop();
ELSE
    HandleUnexpectedState(state);
END_CASE;
```

## When ignoring is legitimate

- Every value outside the listed cases is intentionally ignored.
- The construct is a temporary stub under active development.

In those cases, suppress the finding with a nearby directive and document why
the fallback does not need an action.

## How to fix

Add an `ELSE` branch and choose an explicit policy: log the value, raise an
alarm, select a safe state, return a default, or document an intentional
no-op.

---
title: Stateful function-block assignment
since: 3.1.0
related: [CTS0021, CTS0029]
---

## What it is

An assignment copies one recognized function-block instance to another:

```st
fbTarget := fbSource;
```

## Why it is dangerous

Function blocks carry state between cycles. Copying an instance can also copy
timer state, edge history, counters, retained fields, and outputs. The result
can look like two independently running blocks while both start from the same
history.

The rule reports only assignments where both operands are known FB instances.
Assigning individual fields is not reported:

```st
fbTarget.xEnable := fbSource.xEnable;
```

## Example

```st bad 1
// cts:fb FB_Motor
PROGRAM Main
VAR
    fbSource : FB_Motor;
    fbTarget : FB_Motor;
END_VAR
IMPLEMENTATION
fbTarget := fbSource; // state is copied // cts:here
```

```st good
// cts:fb FB_Motor
PROGRAM Main
VAR
    fbSource : FB_Motor;
    fbTarget : FB_Motor;
END_VAR
IMPLEMENTATION
fbTarget.xEnable := fbSource.xEnable;
```

## When ignoring is legitimate

Ignore only when the FB type is deliberately used as a value object and its
complete internal state is documented as safe to copy.

## How to fix

Call the destination FB with explicit inputs, or copy only the fields whose
transfer is intentional.

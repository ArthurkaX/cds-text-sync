---
title: Floating-point equality
since: 3.0.0
related: []
---

## What it is

An exact equality comparison involving a `REAL` or `LREAL` value.

## Why it is dangerous

Floating-point calculations commonly accumulate small representation and
rounding differences. Two values that are mathematically equal may therefore
not have identical stored bit patterns.

## Example

```st bad 1
PROGRAM Main
VAR
    measured : REAL;
END_VAR
IMPLEMENTATION
IF measured = 0.5 THEN  // cts:here
    DoThing();
END_IF;
```

```st good
PROGRAM Main
VAR
    measured : REAL;
    epsilon : REAL;
END_VAR
IMPLEMENTATION
IF ABS(measured - 0.5) < epsilon THEN
    DoThing();
END_IF;
```

## When ignoring is legitimate

- The value is a deliberately exact sentinel whose representation is known.
- The comparison is part of a protocol or vendor-defined contract.

## How to fix

Compare the absolute difference with a domain-appropriate tolerance, such as
`ABS(a - b) < epsilon`.

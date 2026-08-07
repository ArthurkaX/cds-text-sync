---
title: Implicit TIME and numeric arithmetic
since: 3.1.0
related: [CTS0054, CTS0058]
---

## What it is

An arithmetic expression combines a `TIME` value or literal with a numeric
value without an explicit conversion.

## Why it is dangerous

The numeric value may be interpreted as a duration in an implementation-
dependent way, or the operation may silently lose the intended unit. Millisec-
onds, counts and durations are easy to confuse in PLC code.

## Example

```st bad 1
PROGRAM Main
VAR
    timeout : TIME;
    delayMs : UDINT;
END_VAR
IMPLEMENTATION
timeout := T#5s + delayMs; // cts:here
END_PROGRAM
```

```st good
timeout := T#5s + UDINT_TO_TIME(delayMs);
```

## When ignoring is legitimate

- The target library explicitly defines a numeric operand as milliseconds and
  the project relies on that documented interface.
- The expression is generated code whose conversion convention is validated
  outside the `.st` source.

## How to fix

Convert the numeric value to `TIME` with the appropriate `TO_TIME` or typed
conversion before arithmetic. Convert a `TIME` value to a number only when a
numeric result is explicitly intended.

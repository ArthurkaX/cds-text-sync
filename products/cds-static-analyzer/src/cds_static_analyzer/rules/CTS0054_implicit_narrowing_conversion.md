---
title: Implicit narrowing conversion
since: 3.1.0
related: [CTS0049]
---

## What it is

An assignment copies a known scalar value into a type with a smaller value
range or floating-point precision without an explicit conversion.

## Why it is dangerous

The compiler may accept the assignment while the runtime truncates the value,
wraps it, or loses precision. The rule currently reports direct assignments
between declared scalar variables; complex expressions and user-defined type
aliases are intentionally left for a type-aware expression engine.

## Example

```st bad 2
PROGRAM Main
VAR
    source : DINT;
    target : INT;
    precise : LREAL;
    result : REAL;
END_VAR
IMPLEMENTATION
target := source; // cts:here
result := precise; // cts:here
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    small : INT;
    wide : DINT;
    precise : LREAL;
    result : REAL;
END_VAR
IMPLEMENTATION
wide := small;
result := TO_REAL(precise);
small := TO_INT(wide);
END_PROGRAM
```

## When ignoring is legitimate

- The value is intentionally constrained before the assignment.
- The destination is used as a compact protocol or hardware representation.
- The source and destination are user-defined aliases whose ranges are known
  outside the exported source.

## How to fix

Use the appropriate explicit `TO_` conversion and document any intentional
range restriction.

---
title: Constant arithmetic overflow
since: 3.0.0
related: [CTS0043]
---

## What it is

An arithmetic expression made only from numeric literals is assigned to an
integer type, but its result lies outside that type's representable range.
The check covers declaration initializers and direct assignments.

## Why it is dangerous

The compiler or runtime must narrow the result into the destination type. The
value can wrap, saturate, or be rejected, depending on the target and build
settings. This is a silent data-corruption risk when it is accepted.

## Example

```st bad 1
PROGRAM Main
VAR
    nValue : INT := 30000 + 10000; // cts:here
END_VAR
IMPLEMENTATION
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    nValue : DINT := 30000 + 10000;
END_VAR
IMPLEMENTATION
END_PROGRAM
```

## When ignoring is legitimate

- The assignment is rejected by the compiler before deployment.
- The expression is generated for a target with a documented wrapping rule.
- The value is intentionally converted elsewhere; make that conversion
  explicit so the narrowing is visible.

## How to fix

Use a destination type with a sufficient range, correct the constants, or add
an explicit conversion after validating the intended result.

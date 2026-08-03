---
title: Overwrite without read
tags: [dead-code, suspicious]
since: 3.0.0
related: [CTS0011]
---

## What it is

Two simple assignments to the same variable occur consecutively, so the first
value is overwritten before it can be read.

## Why it is dangerous

The first calculation may be dead code, or the second assignment may be in the
wrong place. This often hides an ordering mistake during refactoring.

## Example

```st bad
PROGRAM P
IMPLEMENTATION
value := CalculateA();
value := CalculateB();
END_PROGRAM
```

```st good
PROGRAM P
IMPLEMENTATION
value := CalculateA();
Use(value);
value := CalculateB();
END_PROGRAM
```

## When ignoring is legitimate

- The second assignment is an explicit self-update, such as
  `counter := counter + 1` or `text := CONCAT(text, suffix)`.
- Self-updates inside `IF`, `CASE`, or loop bodies are also intentional; the
  rule does not compare assignments across control-flow boundaries.
- The first expression is intentionally evaluated for its side effect.
- The code is generated or follows a vendor-specific convention.
- The assignments are placeholders during development.

## How to fix

Remove the obsolete assignment, move the second assignment, or use the first
value before assigning the variable again. Do not remove an assignment without
checking whether its right-hand side has side effects.

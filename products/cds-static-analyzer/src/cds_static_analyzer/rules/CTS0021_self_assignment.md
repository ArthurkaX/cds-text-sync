---
title: Self-assignment
since: 3.0.0
related: [CTS0011, CTS0012]
---

## What it is

A simple assignment writes a variable back to itself, such as `Value :=
Value`. This rule deliberately does not infer equivalence for expressions,
fields, pointers, or function calls.

## Why it is dangerous

The statement has no observable effect and usually indicates a typo, leftover
debug code, or an incomplete refactoring. It can also hide the intended source
variable when names are similar.

## Example

```st bad 1
FUNCTION F : INT
VAR_INPUT
    Value : INT;
END_VAR
IMPLEMENTATION
Value := Value; // cts:here
F := Value;
```

```st good
FUNCTION F : INT
VAR_INPUT
    Value : INT;
END_VAR
VAR
    Result : INT;
END_VAR
IMPLEMENTATION
Result := Value;
F := Result;
```

## When ignoring is legitimate

- Generated code emits the assignment as a harmless compatibility placeholder.
- A vendor-specific runtime gives the assignment an external side effect.

## How to fix

Remove the statement or replace the right-hand side with the intended source
value.

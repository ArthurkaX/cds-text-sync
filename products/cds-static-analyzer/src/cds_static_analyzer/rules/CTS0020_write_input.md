---
title: Write to input variable
since: 3.0.0
related: [CTS0002, CTS0019]
---

## What it is

The POU writes to a variable declared in its `VAR_INPUT` section. The check
also covers assignments to a field or array element rooted at that input.

## Why it is dangerous

Inputs describe data supplied by the caller. Mutating one makes the interface
surprising and can hide a missing local variable or output assignment.

## Example

```st bad 1
FUNCTION Limit : INT
VAR_INPUT
    Value : INT;
END_VAR
IMPLEMENTATION
Value := 0; // cts:here
Limit := Value;
```

```st good
FUNCTION Limit : INT
VAR_INPUT
    Value : INT;
END_VAR
VAR
    Clamped : INT;
END_VAR
IMPLEMENTATION
Clamped := Value;
IF Clamped < 0 THEN
    Clamped := 0;
END_IF;
Limit := Clamped;
```

## When ignoring is legitimate

- The declaration is generated and the external contract intentionally allows
  mutation.
- The POU is being migrated and the write is a temporary compatibility step.

## How to fix

Copy the input into a local variable and modify the local, or assign the
result to a `VAR_OUTPUT`/return value.

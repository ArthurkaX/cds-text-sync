---
title: Missing public POU documentation
since: 3.1.0
related: [CTS0002, CTS0009]
---

## What it is

A public `PROGRAM`, `FUNCTION_BLOCK`, or `FUNCTION`, or one of its interface
parameters (`VAR_INPUT`, `VAR_OUTPUT`, `VAR_IN_OUT`), has no nearby
documentation comment. For the POU that is a comment on its header line, right
below it or right above it: what `cts docs` shows as its description.

## Why it is dangerous

The declaration is the contract other code depends on. Without a short
description, callers must infer units, valid ranges, ownership, and side
effects from the implementation, which makes integration mistakes more likely.

## Example

```st bad 2
PROGRAM Conveyor // cts:here
VAR_INPUT
    Speed : INT; // cts:here
END_VAR
```

```st good
// Starts one conveyor cycle and applies the requested speed in rpm.
PROGRAM Conveyor
VAR_INPUT
    // Requested conveyor speed in rpm.
    Speed : INT;
END_VAR
```

A comment on the header line or right below it counts too, as does one above
an attribute line; they are what `cts docs` shows as the description:

```st good
FUNCTION_BLOCK Valve // Opens and closes one valve with a travel timeout.
VAR_INPUT
    Open : BOOL; // TRUE opens the valve.
END_VAR
```

```st good
// Scales a raw analog value to engineering units.
{attribute 'qualified_only'}
FUNCTION Scale : REAL
VAR_INPUT
    (* Raw value, 0..27648. *)
    Raw : INT;
END_VAR
```

## When ignoring is legitimate

- A generated POU or interface is documented in an external source of truth.
- A private prototype is intentionally short-lived and is not part of the
  project contract.

## How to fix

Add a concise comment before the POU and before each interface parameter, or
add an inline comment after the declaration. Describe purpose, units, valid
ranges, and any ownership or lifetime requirements that callers need to know.

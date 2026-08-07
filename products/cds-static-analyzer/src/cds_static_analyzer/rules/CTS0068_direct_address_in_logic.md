---
title: Direct hardware address in logic
since: 3.1.0
related: [CTS0026]
---

## What it is

Executable Structured Text directly references an IEC hardware address such
as `%IX0.0`, `%QX0.1`, or `%MW10` instead of using a symbolic variable.

## Why it is dangerous

Direct addresses hide hardware mapping inside business logic, making code
harder to review, test, reuse, and migrate between controllers.

## Example

```st bad 1
PROGRAM Main
IMPLEMENTATION
%QX0.1 := xMotor; // cts:here
```

```st good
PROGRAM Main
VAR_GLOBAL
    xMotorOutput AT %QX0.1 : BOOL;
END_VAR
IMPLEMENTATION
xMotorOutput := xMotor;
```

## When ignoring is legitimate

- A dedicated I/O mapping POU intentionally contains the direct access.
- The address is required by generated or vendor-specific integration code.

## How to fix

Move the `AT` mapping to a dedicated declaration or I/O mapping unit and use
the symbolic variable in executable logic.

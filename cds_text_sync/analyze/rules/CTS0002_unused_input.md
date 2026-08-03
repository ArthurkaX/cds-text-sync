---
title: Unused input
since: 3.0.0
related: [CTS0001]
---

## What it is

A `VAR_INPUT` member that is never read by its owner: not in the owner's own
body, and not in any method/action the owner contains. Qualified access
(`THIS.x`, `SUPER^.x`) counts as a read.

## Why it is dangerous

An input is a contract: "this callable consumes this value". An input that
nothing reads is a dead parameter. It forces every caller to invent a value,
it hides bugs (the author *thought* the input was used and wired it up), and
it makes the real interface harder to see. On a function block, an unused
input that is only written (`in := 5;`) does nothing for the caller - a
classic source of "I set the value but nothing happens".

## Example

```st bad 1
FUNCTION_BLOCK FB_Heater
VAR_INPUT
    setpoint : INT;
    alarm_limit : INT;   (* never read *)  // cts:here
END_VAR
VAR_OUTPUT
    heating : BOOL;
END_VAR

IMPLEMENTATION

heating := setpoint > 0;
```

```st good
FUNCTION_BLOCK FB_Heater
VAR_INPUT
    setpoint : INT;
END_VAR
VAR_OUTPUT
    heating : BOOL;
END_VAR

IMPLEMENTATION

heating := setpoint > 0;
```

## When ignoring is legitimate

- The input is part of a vendor or safety contract and must stay even if the
  current implementation does not read it.
- The input is read from a library FB whose methods live outside this project
  view (the rule can only see project-view units).
- The callable is a stub under active development.

## How to fix

Remove the input and update the callers, or - if the input is genuinely
needed by the interface - reference it in the body (and if nothing reads it,
ask why it exists).

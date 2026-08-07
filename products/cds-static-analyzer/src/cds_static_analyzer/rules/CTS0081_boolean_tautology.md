---
title: Tautological or contradictory boolean expression
since: 3.1.0
related: [CTS0010, CTS0048]
---

## What it is

A boolean expression is always true or always false because it combines a
value with its negation or with a boolean constant.

## Why it is dangerous

The expression can make a branch permanently unreachable or make a guard
always pass. In control code this can hide an interlock, a missing condition,
or a copy-paste error.

## Example

```st bad 2
PROGRAM Main
VAR
    ready : BOOL;
    alarm : BOOL;
END_VAR
IMPLEMENTATION
IF ready AND NOT ready THEN // cts:here
    Start := TRUE;
END_IF;
IF alarm OR TRUE THEN // cts:here
    Log := TRUE;
END_IF;
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    ready : BOOL;
    alarm : BOOL;
END_VAR
IMPLEMENTATION
IF ready AND NOT alarm THEN
    Start := TRUE;
END_IF;
IF alarm THEN
    Log := TRUE;
END_IF;
END_PROGRAM
```

## When ignoring is legitimate

- A generated expression deliberately preserves a fixed interface shape.
- The constant is a temporary commissioning switch and is tracked elsewhere.
- The expression is part of a diagnostic assertion whose constant result is
  intentional.

## How to fix

Remove the redundant operand or simplify the expression. If the constant is a
temporary switch, make it a named configuration value and document its role.

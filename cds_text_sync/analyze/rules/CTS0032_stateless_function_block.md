---
title: Stateless function block
---

## What it is

Reports a project `FUNCTION_BLOCK` with no internal state or owned methods.
Such a block has the shape of a stateless `FUNCTION`.

## Why it is dangerous

`FUNCTION_BLOCK` communicates that an object owns state and has a lifecycle.
Using it for a calculation that has no state makes the code harder to read and
can mislead maintainers about what must persist between calls.

## Example

```st bad 1
FUNCTION_BLOCK CalculateSpeed // cts:here
VAR_INPUT
    Distance : REAL;
    Time : REAL;
END_VAR
VAR_OUTPUT
    Speed : REAL;
END_VAR
IMPLEMENTATION
Speed := Distance / Time;
END_FUNCTION_BLOCK
```

```st good
FUNCTION CalculateSpeed : REAL
VAR_INPUT
    Distance : REAL;
    Time : REAL;
END_VAR
IMPLEMENTATION
CalculateSpeed := Distance / Time;
END_FUNCTION
```

## When ignoring is legitimate

- The block is an interface or compatibility boundary whose object shape is
  intentional.
- State is supplied or retained outside the declaration and the FB contract
  is documented accordingly.

## How to fix

Convert the block to a `FUNCTION`, or add an explicit state-owning role when a
function block is genuinely required.

---
title: Pointer guard relies on short-circuit evaluation
---

## What it is

Reports a pointer dereference in the right operand of an `AND` expression
whose left operand checks that the pointer is non-zero.

## Why it is dangerous

Structured Text does not make ordinary `AND` a portable short-circuit
operator. The right operand may still be evaluated when the pointer is zero,
causing an invalid dereference before the condition can reject the branch.

## Example

```st bad 1
PROGRAM Main
VAR
    pData : POINTER TO BYTE;
END_VAR
IMPLEMENTATION
IF pData <> 0 AND pData^ = 16#10 THEN // cts:here
    DoWork();
END_IF;
```

```st good
IF pData <> 0 THEN
    IF pData^ = 16#10 THEN
        DoWork();
    END_IF;
END_IF;
```

## When ignoring is legitimate

- The project explicitly guarantees a short-circuit evaluation mode for every
  target runtime on which the code runs.
- The expression is generated code whose evaluation contract is documented.

## How to fix

Split the null check and the dereference into nested conditions, or use the
project's explicitly supported short-circuit operator when its semantics are
guaranteed by the target.

---
title: Output not assigned on all paths
since: 3.0.0
related: [CTS0009]
---

## What it is

A `VAR_OUTPUT` is assigned in a conditional branch but not on every branch.

## Why it is dangerous

Callers can observe an old or undefined value when the condition is false.
This is especially risky for status, command, and handshake outputs.

## Example

```st bad 1
FUNCTION_BLOCK FB
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
IF Ready THEN
    Done := TRUE; // cts:here
END_IF;
```

```st good
FUNCTION_BLOCK FB
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
IF Ready THEN
    Done := TRUE;
ELSE
    Done := FALSE;
END_IF;
```

## When ignoring is legitimate

- Retaining the previous output value is an explicit interface contract.
- A surrounding generated wrapper guarantees a default before the callable.

## How to fix

Assign a default before the conditional or assign the output in every branch.

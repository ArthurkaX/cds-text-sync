---
title: String literal exceeds declared capacity
since: 3.1.0
related: [CTS0028]
---

## What it is

A string literal is assigned to `STRING(n)` and contains more than `n`
characters.

## Why it is dangerous

The destination cannot represent the complete literal. The value may be
silently truncated or rejected by the compiler, leaving an incomplete command,
identifier, message, or path at runtime.

## Example

```st bad 1
PROGRAM Main
VAR
    deviceName : STRING(4);
END_VAR
IMPLEMENTATION
deviceName := 'PUMP-01'; // cts:here
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    deviceName : STRING(16);
END_VAR
IMPLEMENTATION
deviceName := 'PUMP-01';
END_PROGRAM
```

## When ignoring is legitimate

- The extra characters are intentionally discarded and the truncation is part
  of the interface contract.
- The declaration is generated and its size is controlled by an external
  protocol specification.

## How to fix

Increase the destination capacity or shorten the literal. If truncation is
intentional, document the protocol boundary explicitly.

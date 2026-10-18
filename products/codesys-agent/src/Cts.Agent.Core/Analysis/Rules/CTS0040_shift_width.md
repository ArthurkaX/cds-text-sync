---
title: Shift amount outside operand width
since: 3.1.0
related: []
---

## What it is

`SHL`, `SHR`, `ROL` or `ROR` uses a literal amount greater than or equal to
the known bit width of its operand.

## Why it is dangerous

The result is often zero, unchanged, or target-dependent, and may indicate an
off-by-one error in bit manipulation.

## Example

```st bad 1
VAR
    b : BYTE;
END_VAR
result := SHL(b, 8); // cts:here
```

```st good
result := SHL(b, 7);
```

## When ignoring is legitimate

- The source relies on a documented, target-specific shift convention.
- The code is generated and normalized before deployment.

## How to fix

Use a shift amount from `0` through `width - 1`, or explicitly convert the
operand to a wider type first.

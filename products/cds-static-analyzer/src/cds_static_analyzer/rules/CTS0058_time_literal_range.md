---
title: TIME literal outside range
since: 3.1.0
related: [CTS0042, CTS0049]
---

## What it is

A `T#` or `TIME#` literal is outside the range of a normal 32-bit IEC
`TIME` value. The check supports composed literals such as `T#1d2h30m`.

## Why it is dangerous

The literal cannot be represented by the target type. The compiler may reject
it, truncate it, or produce target-dependent behaviour. A timeout that wraps
or is rejected at build time is especially easy to miss in generated code.

## Example

```st bad 1
PROGRAM Main
VAR
    timeout : TIME := T#50d; // cts:here
END_VAR
IMPLEMENTATION
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    timeout : TIME := T#10d;
END_VAR
IMPLEMENTATION
END_PROGRAM
```

## When ignoring is legitimate

- The target uses a documented wider representation for `TIME`.
- The literal is intentionally rejected by a build-time validation step and
  is not deployed to the PLC.
- The project uses a vendor-specific literal extension with a verified range.

## How to fix

Reduce the duration to the supported range or use the target's documented
wide-duration type when a longer interval is required. Numeric mixing with
`TIME` is intentionally handled by a separate rule.

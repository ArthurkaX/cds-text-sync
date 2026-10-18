---
title: Inadequate FOR counter type
since: 3.1.0
related: [CTS0038, CTS0039]
---

## What it is

A `FOR` loop uses an integer counter whose declared range cannot represent
one of the literal loop bounds.

## Why it is dangerous

The counter can overflow before the loop reaches its boundary. For example,
a `BYTE` counter wraps after `255`; a loop intended to finish at `300` may
therefore never terminate and trigger the PLC watchdog.

## Example

```st bad 1
PROGRAM Main
VAR
    i : BYTE;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 300 DO // cts:here
    Work();
END_FOR;
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    i : UINT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 300 DO
    Work();
END_FOR;
END_PROGRAM
```

## Scope and limitations

The rule checks literal integer bounds and built-in integer counter types.
Dynamic bounds, aliases, and project-specific type ranges are left for a
future type-resolution pass.

## When ignoring is legitimate

- The compiler or runtime uses a wider hidden counter representation and the
  project has verified that the declared type cannot wrap in this loop.
- The loop is intentionally rejected or exited before reaching the offending
  boundary, and that invariant is enforced elsewhere in the code.

## How to fix

Use a counter type whose range contains the complete loop range, such as
`UINT` or `DINT`, or reduce the literal bounds when the smaller range is
intentional.

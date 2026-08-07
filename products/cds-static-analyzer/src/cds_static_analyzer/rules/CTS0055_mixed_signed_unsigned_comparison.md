---
title: Mixed signed and unsigned comparison
since: 3.1.0
related: [CTS0043]
---

## What it is

A comparison uses one signed integer variable and one unsigned integer
variable without an explicit conversion.

## Why it is dangerous

The operands may be promoted to a common type before comparison. A negative
signed value can then be interpreted as a large unsigned value, producing a
result that does not match the apparent source-level intent.

## Example

```st bad 2
PROGRAM Main
VAR
    signedValue : INT;
    unsignedValue : UINT;
    signedCount : DINT;
    unsignedCount : UDINT;
END_VAR
IMPLEMENTATION
IF signedValue < unsignedValue THEN // cts:here
    Accept();
END_IF;
IF signedCount = unsignedCount THEN // cts:here
    Match();
END_IF;
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    signedValue : INT;
    unsignedValue : UINT;
END_VAR
IMPLEMENTATION
IF TO_UINT(signedValue) < unsignedValue THEN
    Accept();
END_IF;
IF signedValue < INT#100 THEN
    Check();
END_IF;
END_PROGRAM
```

## When ignoring is legitimate

- Both values are known to be non-negative by an external protocol or
  invariant.
- The comparison is part of a deliberately unsigned hardware or protocol
  representation.
- The project uses a documented compiler conversion rule intentionally.

## How to fix

Convert one operand explicitly to the intended common type, and handle a
possible negative value before converting a signed operand to unsigned.

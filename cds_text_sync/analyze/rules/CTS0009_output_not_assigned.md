---
title: Output not assigned
since: 3.0.0
related: [CTS0002, CTS0003]
---

## What it is

A `VAR_OUTPUT` member that is never assigned by the callable, its methods, or
its actions. The first version checks direct `:=` assignments and does not
claim that an output is assigned on every possible execution path.

## Why it is dangerous

An output is part of the callable's contract. If the implementation never
writes it, callers may receive a stale value or an interface member that was
forgotten during implementation.

## Example

```st bad 1
FUNCTION_BLOCK FB_Heater
VAR_OUTPUT
    ready : BOOL;  // cts:here
END_VAR

IMPLEMENTATION

IF enable THEN
    start := TRUE;
END_IF;
```

```st good
FUNCTION_BLOCK FB_Heater
VAR_OUTPUT
    ready : BOOL;
END_VAR

IMPLEMENTATION

ready := enable;
```

## When ignoring is legitimate

- The output is reserved for a vendor or safety interface and is intentionally
  untouched by this implementation.
- The output is written by code outside the project view.
- The callable is a stub under active development.

## How to fix

Assign the output as part of the normal implementation, or remove it from the
interface if it is not required. If the value is intentionally retained,
document that decision and suppress the finding locally.

---
title: Unchecked pointer dereference
since: 3.1.0
related: [CTS0051]
---

## What it is

A `POINTER` is dereferenced with `^` without a simple dominating check that
the pointer is non-zero.

## Why it is dangerous

The dereference can fault the task or access an invalid address. On a PLC,
that can stop the task and trip the watchdog.

## Example

```st bad 1
PROGRAM Main
VAR
    pData : POINTER TO BYTE;
END_VAR
IMPLEMENTATION
value := pData^; // cts:here
END_PROGRAM
```

```st good
IF pData <> 0 THEN
    value := pData^;
END_IF;
```

## When ignoring is legitimate

- The pointer is guaranteed non-zero by the caller contract and that
  invariant is enforced at the interface boundary.
- The target runtime defines a valid sentinel address for this pointer.

## How to fix

Check `p <> 0` on the same path before dereferencing, or return from the
invalid branch before continuing with the pointer use.

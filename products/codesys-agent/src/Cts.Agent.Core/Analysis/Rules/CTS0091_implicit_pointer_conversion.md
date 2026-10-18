---
title: Implicit pointer conversion
since: 3.1.0
related: [CTS0060, CTS0063]
---

## What it is

`CTS0091` reports an assignment between pointers with different pointed-to
types when no explicit conversion is visible.

## Why it is dangerous

The destination may apply the wrong alignment, element size, or structure
layout when it is later dereferenced. The resulting fault can be far away from
the assignment that created the invalid view.

## Example

```st bad 1
PROGRAM Main
VAR
    pDint : POINTER TO DINT;
    pReal : POINTER TO REAL;
END_VAR
IMPLEMENTATION
pReal := pDint; // incompatible pointer bases // cts:here
```

```st good
PROGRAM Main
VAR
    pDint : POINTER TO DINT;
    pReal : POINTER TO REAL;
END_VAR
IMPLEMENTATION
// Convert the pointed value explicitly after validating the source.
pReal := DINT_TO_REAL(pDint^);
```

## When ignoring is legitimate

The rule intentionally leaves conversions involving `POINTER TO BYTE` quiet,
because byte pointers are commonly used as generic buffer views. Suppress the
finding when the typed conversion is backed by a documented layout contract.

## How to fix

Keep pointer bases identical, or use a documented explicit conversion after
checking alignment, object size, and lifetime.

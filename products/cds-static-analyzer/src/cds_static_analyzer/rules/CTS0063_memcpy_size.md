---
title: Inconsistent MEMCPY/MemMove size
since: 3.1.0
related: [CTS0026, CTS0060]
---

## What it is

`MEMCPY` or `MemMove` uses a provably oversized copy length, or obtains the
length with `SIZEOF` from a pointer instead of from the pointed object.

## Why it is dangerous

An oversized length lets the copy overwrite adjacent memory. Taking the size
of a pointer produces a value unrelated to the allocated object and can also
silently leave the destination only partly initialized.

## Example

```st bad 1
PROGRAM Main
VAR
    smallBuffer : ARRAY[0..3] OF BYTE;
    source : ARRAY[0..7] OF BYTE;
END_VAR
IMPLEMENTATION
MEMCPY(ADR(smallBuffer), ADR(source), SIZEOF(source)); // cts:here
END_PROGRAM
```

```st bad 1
PROGRAM Main
VAR
    pDestination : POINTER TO BYTE;
    pSource : POINTER TO BYTE;
END_VAR
IMPLEMENTATION
MEMCPY(pDestination, pSource, SIZEOF(pDestination)); // cts:here
END_PROGRAM
```

The first call copies a larger known object into a smaller one. The second
gets the size of the pointer value, not the storage behind it.

## Good example

```st good
PROGRAM Main
VAR
    destination : ARRAY[0..7] OF BYTE;
    source : ARRAY[0..7] OF BYTE;
END_VAR
IMPLEMENTATION
MEMCPY(ADR(destination), ADR(source), SIZEOF(destination));
END_PROGRAM
```

## When ignoring is legitimate

- The destination is a deliberately smaller view and the requested length is
  proven by an external protocol or allocation contract.
- A vendor-specific wrapper validates the length before calling the primitive.

## How to fix

Derive the length from the actual destination object and ensure the source
contains at least that many bytes. For pointers, carry the allocated object
size separately; `SIZEOF(pointer)` cannot recover it.

The rule intentionally stays silent when object sizes or user-defined layout
cannot be proven from the `.st` declarations.

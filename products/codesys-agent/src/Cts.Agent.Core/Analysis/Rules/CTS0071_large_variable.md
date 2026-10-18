---
title: Large variable
since: 3.1.0
related: [CTS0065]
---

## What it is

A variable has a statically known size greater than 1024 bytes. The first
version covers scalar values, strings, and arrays with literal bounds.

## Why it is dangerous

Large local or task-owned values increase memory and stack pressure and can
make a cyclic task harder to schedule predictably.

## Example

```st bad 1
PROGRAM Main
VAR
    Buffer : ARRAY[0..2047] OF BYTE; // cts:here
END_VAR
IMPLEMENTATION
```

```st good
PROGRAM Main
VAR
    Buffer : ARRAY[0..255] OF BYTE;
END_VAR
IMPLEMENTATION
```

## When ignoring is legitimate

- A global buffer is deliberately reserved for a communication protocol.
- The memory budget and task placement have been reviewed explicitly.

## How to fix

Reduce the object, move storage to an appropriate global memory area, or split
the data into smaller structures with an explicit ownership policy.

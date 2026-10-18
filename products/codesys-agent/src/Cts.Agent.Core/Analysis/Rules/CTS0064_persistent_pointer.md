---
title: Retained pointer
since: 3.1.0
related: [CTS0051, CTS0060]
---

## What it is

A pointer is declared in `RETAIN` or `PERSISTENT` storage, or in a persistent
global variable list.

## Why it is dangerous

After a download, restart or memory layout change, the address stored in the
retained variable may no longer point to the original object. The value is
restored even though the pointed storage was not.

## Example

```st bad 1
VAR RETAIN
    pBuffer : POINTER TO BYTE; // cts:here
END_VAR
```

```st good
VAR RETAIN
    bufferId : UDINT;
END_VAR
```

## When ignoring is legitimate

- The pointer is rebuilt from a validated identifier before every use and the
  retained value is never treated as a valid address after restart.
- A target-specific runtime guarantees stable addresses across the exact
  restart and download operations used by the project.

## How to fix

Do not persist raw addresses. Persist an object identifier or offset and
rebuild the pointer during initialization after validating the target.

The rule also covers pointers in a `GVL_PERSISTENT` unit, where persistence is
part of the object kind rather than a qualifier on each declaration block.

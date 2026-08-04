---
title: Overlapping AT memory areas
---

## What it is

Reports two explicit `AT` declarations whose known scalar types occupy the
same bits in the same input, output, or marker memory area.

## Why it is dangerous

Two names can silently refer to the same hardware or process-image bytes.
Writing one variable may change the value observed through another name.

## Example

```st bad 1
VAR_GLOBAL
    Status AT %QB21 : BYTE;
    Count AT %QD5 : DWORD; // cts:here
END_VAR
```

```st good
VAR_GLOBAL
    Status AT %QB21 : BYTE;
    Count AT %QD6 : DWORD;
END_VAR
```

## When ignoring is legitimate

- The aliases are intentional and are part of a documented hardware mapping.
- The overlap is managed through a single owner or a deliberate union-like view.

## How to fix

Give each declaration a non-overlapping address, or keep an intentional alias
in one documented declaration and remove the duplicate mapping.

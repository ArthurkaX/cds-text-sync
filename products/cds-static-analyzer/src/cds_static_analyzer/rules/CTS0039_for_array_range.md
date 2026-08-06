---
title: FOR range exceeds array bounds
since: 3.1.0
related: [CTS0006, CTS0038]
---

## What it is

A literal `FOR` counter range is used to index an array, and the range extends
outside the declared bounds of that dimension. Nested `FOR` loops and direct
indices of multidimensional arrays are supported.

## Why it is dangerous

The loop can perform an out-of-bounds access even though the index expression
is not a literal.

## Example

```st bad 1
VAR
    Values : ARRAY[0..9] OF INT;
    i : INT;
END_VAR
FOR i := 0 TO 10 DO
    Values[i] := 0; // cts:here
END_FOR;
```

```st good
FOR i := 0 TO 9 DO
    Values[i] := 0;
END_FOR;
```

## When ignoring is legitimate

- The loop is unreachable on the deployed target.
- Generated code is narrowed or guarded by a later transformation.

## How to fix

Align the loop limits with the array bounds or guard the access explicitly.
Only literal bounds and direct `array[counter]` or
`array[outerCounter, innerCounter]` accesses are checked here. Complex index
expressions and symbolic array bounds are intentionally skipped.

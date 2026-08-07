---
title: Partial array coverage
since: 3.1.0
related: [CTS0039]
---

# Partial array coverage

## What it is

Detects a literal loop that indexes only part of a declared array.

## Why it is dangerous

The omitted elements may silently retain stale values.

Reports a literal `FOR` loop that indexes only part of a one-dimensional array.

```st bad 1
PROGRAM Main
VAR
    Values : ARRAY[0..9] OF INT;
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 8 DO
    Values[i] := 0; // cts:here
END_FOR;
```

## Example

```st good
PROGRAM Main
VAR
    Values : ARRAY[0..9] OF INT;
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 9 DO
    Values[i] := 0; // cts:here
END_FOR;
```

The rule does not report symbolic bounds, multidimensional arrays, or loops
whose range exceeds the declared array bounds; those cases belong to CTS0039.

## When ignoring is legitimate

Partial processing is valid when the remaining elements are intentionally unused.

## How to fix

Use the complete declared range or document the intended subrange.

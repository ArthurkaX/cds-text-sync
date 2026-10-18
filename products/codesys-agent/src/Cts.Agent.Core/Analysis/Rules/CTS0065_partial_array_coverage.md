---
title: Partial array coverage
since: 3.1.0
related: [CTS0039]
---

# Partial array coverage

## What it is

A `FOR` loop with literal bounds indexes a one-dimensional array with its
counter, and the unit leaves part of the array untouched: an off-by-one end
such as `FOR i := 0 TO 8` over `ARRAY[0..9]`.

The unit's other reaches count: loops over the other slices
(`1..24`, `25..48`, `49..72`), a shifted index (`a[i + 1]`) and a literal
index (`a[1] := x`). A loop that also indexes the array another way
(`a[i + 1]`, or `a[j]` of an inner loop) compares neighbours and stops short
on purpose; it is not reported. Symbolic bounds, multidimensional arrays and
loops past the declared bounds (CTS0039) are not checked.

## Why it is dangerous

The omitted elements may silently retain stale values.

## Example

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

```st good
PROGRAM Main
VAR
    Values : ARRAY[0..9] OF INT;
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 9 DO
    Values[i] := 0;
END_FOR;
```

```st good
PROGRAM Main
VAR
    history : ARRAY[1..10] OF INT;
    sensors : ARRAY[1..6] OF BOOL;
    left, right : INT;
    i, j : INT;
    sample : INT;
END_VAR
IMPLEMENTATION
FOR i := 10 TO 2 BY -1 DO
    history[i] := history[i - 1];
END_FOR;
history[1] := sample;
FOR i := 1 TO 3 DO
    IF sensors[i] THEN left := left + 1; END_IF;
END_FOR;
FOR i := 4 TO 6 DO
    IF sensors[i] THEN right := right + 1; END_IF;
END_FOR;
```

```st good
FUNCTION Duplicates : INT
VAR_INPUT
    codes : ARRAY[0..6] OF INT;
END_VAR
VAR
    i, j : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 5 DO
    FOR j := i + 1 TO 6 DO
        IF codes[i] = codes[j] THEN Duplicates := Duplicates + 1; END_IF;
    END_FOR;
END_FOR;
```

## When ignoring is legitimate

Partial processing is valid when the remaining elements are intentionally unused.

## How to fix

Use the complete declared range or document the intended subrange.

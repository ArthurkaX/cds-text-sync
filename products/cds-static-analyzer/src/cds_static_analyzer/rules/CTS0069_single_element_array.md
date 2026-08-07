---
title: Single-element array
since: 3.1.0
related: [CTS0065]
---

## What it is

A variable is declared as an array whose lower and upper bounds identify the
same single element.

## Why it is dangerous

The array notation adds indexing and bounds without providing storage for a
collection. It obscures the fact that the value is scalar.

## Example

```st bad 1
PROGRAM Main
VAR
    Value : ARRAY[0..0] OF INT; // cts:here
END_VAR
IMPLEMENTATION
```

```st good
PROGRAM Main
VAR
    Value : INT;
END_VAR
IMPLEMENTATION
```

## When ignoring is legitimate

- A generated interface requires a uniform array shape.
- A library contract explicitly requires an array type.

## How to fix

Replace the declaration with the element type and remove the index from uses.

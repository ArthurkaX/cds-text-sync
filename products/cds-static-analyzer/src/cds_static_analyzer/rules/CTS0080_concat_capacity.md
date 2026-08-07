---
title: CONCAT result exceeds string capacity
since: 3.1.0
related: [CTS0028, CTS0078, CTS0079]
---

## What it is

A `CONCAT` expression has a provable maximum length greater than the explicit
capacity of its destination `STRING(n)`. The check supports literals,
explicitly bounded string variables, and nested `CONCAT` calls.

## Why it is dangerous

The result can be truncated before it reaches the next operation. This is
especially easy to miss in message, path, and diagnostic construction where
each individual fragment looks harmless.

## Example

```st bad 1
PROGRAM Main
VAR
    prefix : STRING(8);
    suffix : STRING(8);
    message : STRING(10);
END_VAR
IMPLEMENTATION
message := CONCAT(prefix, suffix); // cts:here
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    prefix : STRING(8);
    suffix : STRING(8);
    message : STRING(16);
END_VAR
IMPLEMENTATION
message := CONCAT(prefix, suffix);
END_PROGRAM
```

## When ignoring is legitimate

- The source values are constrained at runtime more tightly than their
  declarations indicate.
- Truncation is an intentional protocol boundary.
- One of the arguments is produced by an external library and its actual
  length is not visible to the analyzer.

## How to fix

Increase the destination capacity, shorten the input fragments, or validate
the resulting length before assigning it. Make intentional truncation visible
at the boundary where it is required.

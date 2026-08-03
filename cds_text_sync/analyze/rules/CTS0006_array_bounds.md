---
title: Array index outside bounds
tags: [correctness, arrays]
since: 3.0.0
related: [CTS0003]
---

## What it is

A constant array index that is outside the array's declared lower and upper
bounds.

## Why it is dangerous

An out-of-range access can read unrelated memory, overwrite another value, or
cause a runtime exception depending on the target runtime and compiler
checks.

## Example

```st bad
PROGRAM Main
VAR
    values : ARRAY[1..10] OF INT;
END_VAR

IMPLEMENTATION

values[0] := 1;
values[11] := 2;
```

```st good
PROGRAM Main
VAR
    values : ARRAY[1..10] OF INT;
END_VAR

IMPLEMENTATION

values[1] := 1;
values[10] := 2;
```

## When ignoring is legitimate

- The access belongs to generated code whose bounds are validated elsewhere.
- A vendor extension deliberately uses a non-standard access convention.

Suppress the finding only after confirming the target runtime's behavior.

## How to fix

Correct the constant index or correct the array declaration if the declared
range does not represent the intended data structure. Variable indexes are not
judged by this first version of the rule.

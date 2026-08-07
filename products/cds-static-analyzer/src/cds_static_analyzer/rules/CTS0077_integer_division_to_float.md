---
title: Integer division assigned to floating point
since: 3.1.0
related: [CTS0054, CTS0035, CTS0050]
---

## What it is

An expression divides two known integer operands and assigns the result to a
`REAL` or `LREAL` value.

## Why it is dangerous

The integer operation is completed before the assignment. For example,
`5 / 2` becomes `2`, not `2.5`, so converting the result afterward cannot
restore the lost fraction.

## Example

```st bad 1
PROGRAM Main
VAR
    numerator : DINT;
    denominator : DINT;
    ratio : REAL;
END_VAR
IMPLEMENTATION
ratio := numerator / denominator; // cts:here
END_PROGRAM
```

```st good
PROGRAM Main
VAR
    numerator : DINT;
    denominator : DINT;
    ratio : REAL;
END_VAR
IMPLEMENTATION
ratio := TO_REAL(numerator) / denominator;
END_PROGRAM
```

## When ignoring is legitimate

- Integer quotient semantics are intentional and the floating-point target is
  only a storage or interface requirement.
- The source operands are known to divide evenly.

## How to fix

Convert one operand explicitly with `TO_REAL` or `TO_LREAL` before division.
Keep the zero-divisor checks required by the surrounding code as well.

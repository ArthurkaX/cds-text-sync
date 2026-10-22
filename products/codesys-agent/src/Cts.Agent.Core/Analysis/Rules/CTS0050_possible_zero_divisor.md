---
title: Possible zero divisor
since: 3.0.0
related: [CTS0035]
---

## What it is

A division uses a variable divisor without a simple proof on the current path
that the divisor is non-zero. Literal zero remains the responsibility of
CTS0035.

This rule recognizes direct `IF divisor <> 0` guards, complementary `ELSE`
branches after `IF divisor = 0`, and guard clauses that leave the routine or
loop when the divisor is zero. A local declared with a non-zero value that no
code assigns, passes by reference or names from a screen holds that value
always, so it needs no guard.

## Why it is dangerous

The divisor may become zero at runtime, causing a fault, an invalid result, or
a task watchdog trip depending on the target runtime.

## Example

```st bad 1
result := value / divisor; // cts:here
```

```st good
IF divisor = 0 THEN
    RETURN;
END_IF;
result := value / divisor;
```

```st good
IF divisor <> 0 THEN
    result := value / divisor;
END_IF;
```

An early exit on a BOOL set before it from the check counts the same, through
`OR` and `NOT`, while the divisor is not assigned between:

```st good
error := NOT (divisor > 0.0) OR span <= 0.0;
IF error THEN
    RETURN;
END_IF;
result := value / divisor;
```

A type conversion is looked through: its argument is the divisor. A constant
declared with a non-zero value needs no guard, and another call's result is
not a variable this rule follows:

```st bad 1
average := total / DINT_TO_REAL(count); // cts:here
```

```st good
VAR CONSTANT
    PERIOD_NS : ULINT := 200000000;
END_VAR
VAR
    share : LINT;
    worst : LINT;
END_VAR
IMPLEMENTATION
share := worst * 1000 / ULINT_TO_LINT(PERIOD_NS);
share := worst / PERIOD_NS;
share := worst / Samples();
```

A divisor whose last assignment on the path gives a value that is never zero
needs no guard either: a non-zero number or constant, a conversion of a
divisor already safe, `LIMIT` with a positive low bound or `MAX` with a
positive argument. An `IF` without `ELSE` that sets a non-zero value when the
divisor would be zero counts too, so a clamp makes it safe:

```st good
VAR CONSTANT
    MIN_ITER : ULINT := 10;
END_VAR
VAR
    raw : ULINT;
    count : UDINT;
    steps : DINT;
    total : ULINT;
    share : ULINT;
END_VAR
IMPLEMENTATION
IF raw < MIN_ITER THEN
    raw := MIN_ITER;
END_IF;
IF raw > 1000 THEN
    raw := 1000;
END_IF;
count := ULINT_TO_UDINT(raw);
share := total / count;
steps := LIMIT(1, steps, 50);
share := total / steps;
```

A guard may compare with a named constant as well as with a number, and the
ELSE of a test that zero meets is guarded:

```st good
VAR CONSTANT
    MIN_COUNT : INT := 1;
END_VAR
VAR
    count : INT;
    total : INT;
    share : INT;
END_VAR
IMPLEMENTATION
IF count >= MIN_COUNT THEN
    share := total / count;
END_IF;
IF count <= 0 THEN
    share := 0;
ELSE
    share := total / count;
END_IF;
```

A clamp from above only, or an assignment on another branch, proves nothing:

```st bad 2
VAR
    raw : ULINT;
    count : UDINT;
    total : ULINT;
    share : ULINT;
    ready : BOOL;
END_VAR
IMPLEMENTATION
IF raw > 1000 THEN
    raw := 1000;
END_IF;
share := total / raw; // cts:here
IF ready THEN
    count := 5;
END_IF;
share := total / count; // cts:here
```

## When ignoring is legitimate

- A preceding contract guarantees that the divisor is non-zero but that
  contract is not represented in Structured Text.
- A library call validates or replaces the divisor indirectly.
- The target runtime deliberately defines the zero-division result.

## How to fix

Validate the divisor immediately before use, return or take an alternate path
when it is zero, or make the non-zero contract explicit in the code.

Complex boolean guards and interprocedural validation are intentionally left to
a future data-flow improvement.

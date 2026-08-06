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
loop when the divisor is zero.

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

---
title: Division by literal zero
since: 3.1.0
related: [CTS0017]
---

## What it is

An expression divides by a numeric literal whose value is zero, including
typed zero literals such as `DINT#0`.

## Why it is dangerous

The operation can raise a runtime error or produce target-dependent behaviour.

## Example

```st bad 1
result := value / 0; // cts:here
```

```st good
IF divisor <> 0 THEN
    result := value / divisor;
END_IF;
```

## When ignoring is legitimate

- Generated code deliberately contains a target-specific zero divisor that is
  never executed.
- The source is an intermediate representation checked by another tool.

## How to fix

Use a non-zero divisor or validate the divisor before the operation.

This rule intentionally handles only literal zero. Path-sensitive checks for a
possibly-zero variable belong to a separate data-flow rule.

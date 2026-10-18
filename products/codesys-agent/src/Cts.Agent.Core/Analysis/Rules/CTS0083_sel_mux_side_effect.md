---
title: SEL/MUX argument may have side effects
---

## What it is

Reports a call with possible side effects inside a value argument of `SEL` or
`MUX`.

## Why it is dangerous

`SEL` and `MUX` are expressions, not lazy branches. Their arguments can be
evaluated before the selector chooses the result. A function-block call or a
non-pure function in an unused argument can therefore change state, consume an
input, trigger I/O, or perform work unexpectedly.

## Example

```st bad 1
result := SEL(UseNew, ReadOld(), UpdateAndReadNew()); // cts:here
```

```st good
IF UseNew THEN
    result := UpdateAndReadNew();
ELSE
    result := ReadOld();
END_IF;
```

## When ignoring is legitimate

- Every argument call is documented as pure and free of state changes.
- Evaluation of all arguments is intentional and harmless.

## How to fix

Evaluate side-effecting calls in an explicit `IF`/`CASE` branch, then pass
already computed values to `SEL`/`MUX`. The rule is deliberately conservative
for calls whose purity cannot be proven locally.

---
title: Constant control-flow expression
since: 3.0.0
related: [CTS0017, CTS0047]
---

## What it is

An `IF`, `ELSIF`, or `WHILE` condition consists entirely of constants and can
be evaluated before the program runs. Literal `TRUE` and `FALSE` are left to
CTS0017; self-comparisons such as `value = value` are left to CTS0047.

## Why it is dangerous

One branch is permanently selected or permanently skipped. This can hide a
configuration mistake, dead code, or a partially edited condition.

## Example

```st bad 2
IF 10 < 20 THEN // cts:here
    Run();
END_IF;
IF (2 + 3) = 5 THEN // cts:here
    Log();
END_IF;
```

```st good
IF limit < 20 THEN
    Run();
END_IF;
IF item_count = expected_count THEN
    Log();
END_IF;
```

## When ignoring is legitimate

- Generated code deliberately uses a compile-time feature switch.
- A temporary commissioning branch is intentionally constant.
- The condition depends on a value that is not represented as a literal in
  the source; it is outside this rule's scope.

## How to fix

Remove the dead branch, replace the constant with the intended variable or
configuration value, or document and suppress the generated condition.

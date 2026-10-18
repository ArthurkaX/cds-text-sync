---
title: Comparison outside type range
since: 3.1.0
related: [CTS0017]
---

## What it is

A comparison with a literal has the same result for every value representable
by the variable's known integer type.

## Why it is dangerous

The condition may be dead, may hide a wrong type or bound, and can make the
control flow misleading.

## Example

```st bad 1
VAR
    count : UINT;
END_VAR
IF count >= 0 THEN // cts:here
    Run();
END_IF;
```

```st good
IF count > 0 THEN
    Run();
END_IF;
```

## When ignoring is legitimate

- The comparison documents an external contract or generated-code invariant.
- The variable's declared type is deliberately wider than its current use.

## How to fix

Correct the bound, simplify the condition, or use the intended variable type.

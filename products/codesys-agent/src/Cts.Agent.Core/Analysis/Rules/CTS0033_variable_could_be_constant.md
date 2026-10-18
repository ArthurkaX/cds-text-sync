---
title: Variable could be declared CONSTANT
since: 3.0.0
related: [CTS0012, CTS0013]
---

## What it is

A local variable has a constant initializer and no detected assignment or
possible aliasing use. It may communicate its intent more clearly as a
`CONSTANT` declaration.

The first version is deliberately conservative: it checks local `VAR`,
`VAR_TEMP`, and `VAR_STAT` members with literal constant expressions. Inputs,
outputs, globals, `AT` variables, retained variables, references, pointers,
arrays, and variables passed to calls are excluded.

## Why it is dangerous

This is primarily a readability issue. A mutable declaration suggests that
the value may change, which makes code review and maintenance harder. The
explicit `CONSTANT` form records the intended invariant for readers and tools.

## Example

```st bad 1
FUNCTION Calculate : INT
VAR
    MaxRetries : INT := 3; // cts:here
    Result : INT;
END_VAR
IMPLEMENTATION
Result := MaxRetries + 1;
Calculate := Result;
```

```st good
FUNCTION Calculate : INT
VAR CONSTANT
    MaxRetries : INT := 3;
END_VAR
VAR
    Result : INT;
END_VAR
IMPLEMENTATION
Result := MaxRetries + 1;
Calculate := Result;
```

## When ignoring is legitimate

- The declaration is part of generated or vendor-specific source.
- The variable is intentionally kept mutable for a future configuration.
- External tooling relies on the declaration being a regular variable.
- The value may be changed through an interface or alias not visible to the
  analyzer.

## How to fix

Confirm that the value is not changed through an external mechanism, then move
the declaration into a `VAR CONSTANT` block. If it is intentionally mutable,
leave it as-is or suppress this style finding for the source file.

---
title: Ignored function return value
since: 3.0.0
related: [CTS0009]
---

## What it is

A project `FUNCTION` is called as a standalone statement, so its return value
is not used by the caller.

This rule is disabled by default. IEC Structured Text has no `VOID` function
type, so projects commonly use functions for procedure-like operations with
side effects. Run `CTS0034` explicitly when the project convention requires
every function result to be handled.

## Why it is dangerous

The caller may accidentally discard a status, error code, or calculated value.
The analyzer only reports standalone calls to functions defined in the visible
project; function-block calls and unknown library calls are not reported.

## Example

```st bad 1
FUNCTION Run : BOOL
IMPLEMENTATION
// cts:function CheckLimits
CheckLimits(10); // cts:here
Run := TRUE;
END_FUNCTION
```

```st good
FUNCTION Run : BOOL
VAR
    LimitsOk : BOOL;
END_VAR
IMPLEMENTATION
LimitsOk := CheckLimits(10);
Run := LimitsOk;
END_FUNCTION
```

## When ignoring is legitimate

- The function performs an intentional side effect and has no `VOID` form.
- The return value is documented as optional or informational.
- The function is a compatibility wrapper around a procedure-like API.
- The project deliberately permits procedure-style functions.

## How to fix

Assign the return value and handle it, or document and suppress the finding
when the call is intentionally procedure-like. If this is the project-wide
convention, leave the rule disabled in the default policy.

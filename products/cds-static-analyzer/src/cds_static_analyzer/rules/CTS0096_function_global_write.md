---
title: Function writes global state
since: 3.1.0
related: [CTS0025]
---

## What it is

`CTS0096` reports a `FUNCTION` that writes a project-global variable or one of
its fields.

## Why it is dangerous

Callers usually treat a `FUNCTION` as a calculation. A hidden global write
breaks that expectation, makes repeated calls order-dependent, and can create
side effects in a task that are not visible in the function signature.

## Example

```st bad 1
VAR_GLOBAL
    gCalls : UDINT;
END_VAR

FUNCTION NextValue : UDINT
IMPLEMENTATION
gCalls := gCalls + 1; // hidden global side effect // cts:here
NextValue := gCalls;
```

```st good
FUNCTION NextValue : UDINT
VAR_INPUT
    currentCalls : UDINT;
END_VAR
IMPLEMENTATION
NextValue := currentCalls + 1;
```

## When ignoring is legitimate

Ignore deliberate instrumentation, compatibility wrappers, or platform APIs
whose side effect is part of the documented function contract. A local
variable with the same name as a global is not reported.

## How to fix

Return the new value or pass mutable state through an explicit parameter. If a
side effect is required, expose it through a `FUNCTION_BLOCK` or a clearly
named procedure-style POU.

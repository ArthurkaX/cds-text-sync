---
title: Redundant boolean IF
since: 3.0.0
related: [CTS0007, CTS0008]
---

## What it is

An `IF` with an `ELSE` branch where both branches assign opposite boolean
constants to the same variable. The condition may be a complex or
multi-line expression. `ELSIF` chains are not part of this rule.

## Why it is dangerous

The longer form hides the fact that the variable is simply the value of a
boolean expression. It adds visual noise and can make readers search for
logic that is not actually present.

## Example

```st bad 1
IF (AutoMode AND NOT ErrorActive) OR ForceStart THEN  // cts:here
    CanStart := TRUE;
ELSE
    CanStart := FALSE;
END_IF;
```

```st good
CanStart := (AutoMode AND NOT ErrorActive) OR ForceStart;
```

## When ignoring is legitimate

- The explicit branches are required by a local coding standard.
- The branches carry comments that explain an important operational decision.
- The block is intentionally kept expanded while debugging or teaching the
  sequence.

## How to fix

Assign the condition directly to the boolean variable. If the values are
reversed, assign `NOT (condition)` instead. Keep the original form when the
branches contain any additional statements or meaningful branch-specific
comments.

---
title: Function-block output read before call
since: 3.1.0
related: [CTS0031, CTS0042]
---

## What it is

A stateful function-block field is read before the instance is called in the
current implementation cycle. Standard timer and edge-trigger blocks are
recognized, as are output fields declared by project function blocks.

## Why it is dangerous

The field still contains the previous cycle's value, an initialization value,
or an undefined value. The resulting logic can lag by one cycle or react to a
stale edge.

## Example

```st bad 1
PROGRAM Main
VAR
    timer : TON;
END_VAR
IMPLEMENTATION
IF timer.Q THEN // cts:here
    Done := TRUE;
END_IF;
timer(IN := Enable, PT := T#1s);
```

```st good
timer(IN := Enable, PT := T#1s);
IF timer.Q THEN
    Done := TRUE;
END_IF;
```

## When ignoring is legitimate

- The previous-cycle value is intentionally used; document that temporal
  dependency and suppress the finding.
- The instance is called by generated or surrounding code that is not present
  in the analyzed `.st` unit.

## How to fix

Call the timer, trigger, or function block before consuming its stateful output
in the cycle. For edge triggers, provide the input and call the instance at a
stable point on every cycle.

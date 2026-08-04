---
title: Multiple calls to one function-block instance
---

## What it is

Reports a direct call to the same `FUNCTION_BLOCK` instance more than once in
one sequential control-flow context.

## Why it is dangerous

Each call can advance timers, edge detectors, counters, and other internal
state. Calling the instance twice can make it observe two different inputs in
one cycle or skip the state a caller expected to read.

## Example

```st bad 1
// cts:fb TON
FUNCTION Run : BOOL
VAR
    Timer : TON;
END_VAR
IMPLEMENTATION
Timer(IN := TRUE);
Timer(IN := FALSE); // cts:here
Run := Timer.Q;
```

```st good
// cts:fb TON
FUNCTION Run : BOOL
VAR
    Timer : TON;
END_VAR
IMPLEMENTATION
IF Enabled THEN
    Timer(IN := TRUE);
ELSE
    Timer(IN := FALSE);
END_IF;
Run := Timer.Q;
```

## When ignoring is legitimate

- The repeated calls are deliberately part of a state-machine or protocol
  step.
- The calls are actually separated by mutually exclusive branches.

## How to fix

Call the instance once per execution path, calculate its inputs first, and
read its outputs after that call. If two updates are required, document the
intent and suppress the finding locally.

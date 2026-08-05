---
title: Conditional function-block call
---

## What it is

Reports a `FUNCTION_BLOCK` instance called inside an `IF` or `CASE` branch.

## Why it is dangerous

Stateful blocks such as timers, edge detectors, counters, and communication
blocks normally need to execute every cycle. A conditional call can freeze the
instance state while its condition is false.

## Example

```st bad 1
// cts:fb TON
FUNCTION Run : BOOL
VAR
    Timer : TON;
END_VAR
IMPLEMENTATION
IF Enabled THEN
    Timer(IN := TRUE); // cts:here
END_IF;
Run := Timer.Q;
```

```st good
FUNCTION Run : BOOL
VAR
    Timer : TON;
END_VAR
IMPLEMENTATION
Timer(IN := Enabled);
Run := Timer.Q;
```

## When ignoring is legitimate

- The conditional call intentionally pauses or freezes the block.
- The block is documented as not requiring cyclic execution.

## How to fix

Call the instance on every cycle and pass the condition as an input, or make
the block lifetime and pause behavior explicit.

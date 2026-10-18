---
title: Conditional function-block call
---

## What it is

Reports a function-block instance called inside an `IF` or `CASE` branch when
it holds a clock: a library timer, counter or PID (`TON`, `TOF`, `TP`, `CTU`,
`CTD`, `CTUD`, `PID`, ...), or a project function block that declares one,
however deep. Edge detectors, bistables and blocks without a clock are left
alone: a state machine calls them in its branches by design.

## Why it is dangerous

Stateful blocks such as timers, edge detectors, counters, and communication
blocks normally need to execute every cycle. A conditional call can freeze the
instance state while its condition is false.

## Example

```st bad 1
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

```st bad 1
PROGRAM Conveyor
VAR
    state : INT;
    delay : FB_Delay;
END_VAR
IMPLEMENTATION
CASE state OF
    1: delay(); // cts:here
END_CASE;
FUNCTION_BLOCK FB_Delay
VAR
    Timer : TON;
END_VAR
IMPLEMENTATION
Timer(IN := TRUE, PT := T#1S);
```

```st good
// cts:fb FB_Step
PROGRAM Main
VAR
    state : INT;
    step : FB_Step;
    edge : R_TRIG;
END_VAR
IMPLEMENTATION
CASE state OF
    1: step();
    2: edge(CLK := TRUE);
END_CASE;
```

A state machine that starts its timeout in one state, waits on it in the
next and resets it by hand (`IN := FALSE`, or `RESET`/`LOAD := TRUE` for a
counter) manages the timer's lifetime itself and is left alone. Otherwise an
instance is reported once, at its first conditional call:

```st good
PROGRAM Main
VAR
    state : INT;
    timeout : TON;
    acknowledged : BOOL;
END_VAR
IMPLEMENTATION
CASE state OF
    0:
        timeout(IN := FALSE);
        state := 1;
    1:
        timeout(IN := TRUE, PT := T#2S);
        IF acknowledged OR timeout.Q THEN
            timeout(IN := FALSE);
            state := 0;
        END_IF;
END_CASE;
```

```st bad 1
PROGRAM Main
VAR
    state : INT;
    delay : TON;
END_VAR
IMPLEMENTATION
CASE state OF
    1: delay(IN := TRUE, PT := T#1S); // cts:here
    2: delay(IN := TRUE, PT := T#2S);
END_CASE;
```

## When ignoring is legitimate

- The conditional call intentionally pauses or freezes the block.
- The block is documented as not requiring cyclic execution.

## How to fix

Call the instance on every cycle and pass the condition as an input, or make
the block lifetime and pause behavior explicit.

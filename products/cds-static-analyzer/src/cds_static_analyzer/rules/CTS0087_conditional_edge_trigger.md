---
title: Conditional edge-trigger call
since: 3.1.0
related: [CTS0031, CTS0052]
---

## What it is

`CTS0087` reports an `R_TRIG` or `F_TRIG` call nested inside conditional or
loop control flow. Such an edge detector is not guaranteed to execute exactly
once on every cyclic-task scan.

## Why it is dangerous

The trigger stores the previous input state internally. If it is skipped, or
called several times in one scan, a short-lived edge can be missed or consumed
at the wrong point. That can prevent a command, reset, or safety transition
from being processed.

## Example

```st bad 1
PROGRAM Main
VAR
    rStart : R_TRIG;
END_VAR
IMPLEMENTATION
IF Enable THEN
    rStart(CLK := StartInput); // may be skipped for a scan // cts:here
END_IF;

IF rStart.Q THEN
    StartMotor := TRUE;
END_IF;
```

```st good
PROGRAM Main
VAR
    startTrigger : R_TRIG;
END_VAR
IMPLEMENTATION
startTrigger(CLK := StartInput);
IF startTrigger.Q THEN
    StartMotor := TRUE;
END_IF;
```

## When ignoring is legitimate

Ignore only when the surrounding control flow is proven to execute exactly
once per cycle, or when the trigger is intentionally used as a local event
filter rather than a scan-wide edge detector.

## How to fix

Call the trigger unconditionally near the start of the cyclic POU, then use
its `.Q` output inside later conditions. If a loop is required, feed the
trigger from a separate once-per-cycle stage.

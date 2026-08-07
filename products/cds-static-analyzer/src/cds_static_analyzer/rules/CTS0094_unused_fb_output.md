---
title: Unused function-block output
since: 3.1.0
related: [CTS0009, CTS0013]
---

## What it is

`CTS0094` reports a `VAR_OUTPUT` of a project function block that has no
external `instance.Output` read in the analyzed Structured Text.

## Why it is dangerous

An output that no consumer reads may be a forgotten interface signal, a stale
diagnostic contract, or a copy-paste declaration. Keeping unused outputs also
makes the FB's public behavior harder to understand.

The check is deliberately limited to recognized FB instances in other POU
declarations. It does not treat an output's use inside its own FB as an
external consumer.

## Example

```st bad 1
FUNCTION_BLOCK FB_Motor
VAR_OUTPUT
    xDone : BOOL;
END_VAR
IMPLEMENTATION
xDone := TRUE;
// No POU reads motor.xDone. // cts:here
```

```st good
FUNCTION_BLOCK FB_Motor
VAR_OUTPUT
    xDone : BOOL;
END_VAR
IMPLEMENTATION
xDone := TRUE;

PROGRAM Main
VAR
    motor : FB_Motor;
END_VAR
IMPLEMENTATION
IF motor.xDone THEN
    StartNextStep();
END_IF;
```

## When ignoring is legitimate

Ignore outputs consumed by HMI, visualization, fieldbus mapping, watch lists,
or another project that is not present in the exported `.st` view. Public FB
interfaces may intentionally expose signals before an internal consumer exists.

## How to fix

Remove the output, consume it explicitly, or document the external consumer
that is outside the analyzed project.

---
title: Unused function-block output
since: 3.1.0
related: [CTS0009, CTS0013]
---

## What it is

`CTS0094` reports a `VAR_OUTPUT` of a project function block that has no
external `instance.Output` read in the analyzed Structured Text or in the
visualization XML of the project view.

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
    xDone : BOOL; // cts:here
END_VAR
IMPLEMENTATION
xDone := TRUE;
// No POU reads motor.xDone.
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

In CODESYS HMI projects an FB output is very often read only by a
visualization element. The analyzer now consults the visualization XML of the
project view (for example `project-view/Runtime/PLC Logic/Application/HMI/
Screen1.xml`): an output that is bound by a screen element such as
`Main.pump.running` is treated as consumed and is not reported, even when no
`.st` file reads it.

The visualization match is deliberately textual and approximate: it looks for
dotted identifier paths in the XML and considers an output used if it appears.
It can therefore miss a genuinely dead output that happens to be named in a
screen, which is the acceptable direction of error for a `suspicious` rule.
Fieldbus mappings, watch lists, and other external tooling are still invisible
to the analyzer: an output consumed only by those is still reported. Public FB
interfaces may intentionally expose signals before an internal consumer exists.
An output explicitly discarded in a named call mapping (`Output => ,`) is also
treated as intentional and is not reported.

## How to fix

Remove the output, consume it explicitly, or document the external consumer
that is outside the analyzed project view (for example a fieldbus mapping or a
watch list that the analyzer cannot see).

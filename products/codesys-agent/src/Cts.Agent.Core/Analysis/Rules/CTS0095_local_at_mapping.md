---
title: Local variable uses AT hardware mapping
since: 3.1.0
related: [CTS0026, CTS0068]
---

## What it is

`CTS0095` reports an `AT %IX/%QX/%MW` mapping declared in a local POU
variable block.

## Why it is dangerous

Local hardware mappings mix physical I/O layout with reusable application
logic. They are harder to review, test, remap, and reuse than a single global
I/O mapping layer.

## Example

```st bad 1
PROGRAM Main
VAR
    xMotor AT %QX0.1 : BOOL; // local hardware coupling // cts:here
END_VAR
IMPLEMENTATION
xMotor := TRUE;
```

```st good
VAR_GLOBAL
    xMotor AT %QX0.1 : BOOL;
END_VAR

PROGRAM Main
VAR
    xMotorCommand : BOOL;
END_VAR
IMPLEMENTATION
xMotorCommand := TRUE;
```

## When ignoring is legitimate

Ignore dedicated low-level driver POUs or vendor-generated projections whose
purpose is explicitly to bind local variables to hardware. Global I/O maps and
`VAR_INPUT`/`VAR_OUTPUT` interface declarations are not reported.

## How to fix

Move the `AT` declaration to a dedicated global mapping unit and pass symbolic
signals into the POU.

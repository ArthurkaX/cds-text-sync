---
title: VAR_IN_OUT never written
since: 3.1.0
related: [CTS0020, CTS0073]
---

## What it is

A `VAR_IN_OUT` parameter is read but never written by its POU: no
assignment, no output mapping (`=> param`), no passing to a callee's
`VAR_IN_OUT`, no call of it or of its methods (an instance passed in changes
when called). A small scalar with that contract
is better represented as `VAR_INPUT`; a structure, array or string keeps its
reference, and saves the copy, as `VAR_IN_OUT CONSTANT`, which this rule
leaves alone.

## Why it is dangerous

`VAR_IN_OUT` tells callers that the POU may modify their storage. Keeping that
stronger aliasing contract when no write occurs makes interfaces harder to
understand and can hide unnecessary coupling between POUs.

## Example

```st bad 1
FUNCTION IsReady : BOOL
VAR_IN_OUT
    ioState : INT; // cts:here
END_VAR
IMPLEMENTATION
IsReady := ioState > 0;
```

```st good
FUNCTION IsReady : BOOL
VAR_INPUT
    state : INT;
END_VAR
IMPLEMENTATION
IsReady := state > 0;
```

```st bad 1
FUNCTION Total : DINT
VAR_IN_OUT
    table : ARRAY[1..840] OF DINT; // cts:here
END_VAR
VAR
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 1 TO 840 DO
    Total := Total + table[i];
END_FOR;
```

```st good
FUNCTION Total : DINT
VAR_IN_OUT CONSTANT
    table : ARRAY[1..840] OF DINT;
END_VAR
VAR
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 1 TO 840 DO
    Total := Total + table[i];
END_FOR;
```

```st good
// cts:fb FB_Axis
// cts:method FB_Axis: Stop
FUNCTION Halt : BOOL
VAR_IN_OUT
    axis : FB_Axis;
END_VAR
IMPLEMENTATION
axis.Stop();
Halt := TRUE;
```

Handing it on to a project callee's `VAR_IN_OUT` counts as a write too, since
the callee may change it; to a `VAR_IN_OUT CONSTANT` or a `VAR_INPUT` it does
not:

```st good
FUNCTION_BLOCK Logger
VAR_IN_OUT
    table : ARRAY[1..840] OF DINT;
END_VAR
IMPLEMENTATION
table[1] := 0;
FUNCTION_BLOCK Cell
VAR_IN_OUT
    stats : ARRAY[1..840] OF DINT;
END_VAR
VAR
    log : Logger;
END_VAR
IMPLEMENTATION
log(table := stats);
```

```st bad 1
FUNCTION Sum : DINT
VAR_IN_OUT CONSTANT
    table : ARRAY[1..840] OF DINT;
END_VAR
IMPLEMENTATION
Sum := table[1];
FUNCTION Report : DINT
VAR_IN_OUT
    stats : ARRAY[1..840] OF DINT; // cts:here
END_VAR
IMPLEMENTATION
Report := Sum(stats);
```

## When ignoring is legitimate

- The parameter is part of a stable public interface and must retain its
  `VAR_IN_OUT` contract for compatibility, such as the parameter of a system
  event's function (`EventPrm`), whose signature the task configuration sets.
- A write happens through a library call or generated code whose formal
  parameter directions are unavailable to the analyzer.

## How to fix

Change the declaration to `VAR_INPUT` (a small scalar) or `VAR_IN_OUT
CONSTANT` (anything larger) when the value is read-only. If the POU
is intended to update the caller's storage, add the missing assignment or
make that mutation explicit in the implementation.

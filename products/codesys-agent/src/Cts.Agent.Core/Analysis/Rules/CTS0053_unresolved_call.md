---
title: Unresolved call
since: 3.1.0
related: [CTS0045]
---

## What it is

A call cannot be resolved to a POU in the project or to a known IEC/CODESYS
library symbol. Standard functions, standard function blocks, and explicit
type-conversion functions are excluded from this check, and so is a call a
library in the project's Library Manager can hold: one through the library's
namespace (`DED.GetStatus()`), or a system component's function named after
it (`SysTimeGetNs` from SysTimeCore, `IecTaskGetInfo3` from CmpIecTask).

## Why it is dangerous

The call may be a misspelled or deleted POU, a missing library dependency, or a
method whose receiver type is not what the code expects. The analyzer reports
this with low severity because external vendor libraries are not always
available in the exported `.st` project view.

## Example

```st bad 1
PROGRAM Main
IMPLEMENTATION
UpdateSate(); // cts:here
```

```st good
PROGRAM Main
IMPLEMENTATION
UpdateState(); // cts:function UpdateState
```

A call reaches a method through a program's instance (`Line.valve.Open()`),
and a function block calls its own or an inherited method or action by the
bare name, though other blocks have methods of the same name:

```st good
// cts:fb FB_Valve
// cts:method FB_Valve: Open
PROGRAM Cell
VAR
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO (SHR(8, 1)) DO
    Line.valve.Open();
END_FOR;
PROGRAM Line
VAR
    valve : FB_Valve;
END_VAR
IMPLEMENTATION
valve();
```

```st good
// cts:fb FB_Base
// cts:fb FB_Fan
// cts:method FB_Base: Reset
// cts:method FB_Pump: Start
// cts:method FB_Fan: Reset
// cts:method FB_Fan: Start
FUNCTION_BLOCK FB_Pump EXTENDS FB_Base
VAR
    running : BOOL;
END_VAR
IMPLEMENTATION
IF NOT running THEN
    Start();
END_IF;
Reset();
```

## When ignoring is legitimate

- The call belongs to a vendor library or runtime extension that is not part
  of the analyzed project view.
- The call is generated or bound by the target runtime.
- A dynamic dispatch mechanism resolves the symbol outside static analysis.

## How to fix

Correct the spelling, export the missing library declaration, or configure the
project view so the external dependency is available. Suppress the finding
when the external call is intentional and documented.

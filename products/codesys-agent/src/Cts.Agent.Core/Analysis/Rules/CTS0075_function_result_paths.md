---
title: Function result not assigned on all paths
since: 3.1.0
related: [CTS0009, CTS0019]
---

## What it is

A `FUNCTION` assigns its result variable only in some branches, or never
assigns it at all. The result variable has the same name as the function. A
`METHOD` with a result type counts when it assigns the result in some
branches only. An `IF` or `CASE` covers all paths when every branch assigns
and it has an `ELSE`, or, for an `IF`, when its conditions over boolean
variables leave no case out (`NOT ready`, `ready AND busy`, `ready AND NOT
busy`); a comparison or a call in a condition keeps it open. A loop covers them when its body surely runs once, a `REPEAT` or a
`FOR` over literal bounds, and assigns before every `EXIT` too.

## Why it is dangerous

Callers receive an undefined, stale, or default value on the path without an
assignment. The error is often hidden because the successful path appears to
work during a quick test.

## Example

```st bad 1
FUNCTION GetValue : INT
VAR_INPUT
    ok : BOOL;
END_VAR
IMPLEMENTATION
IF ok THEN
    GetValue := 42; // cts:here
END_IF;
```

```st good
FUNCTION GetValue : INT
VAR_INPUT
    ok : BOOL;
END_VAR
IMPLEMENTATION
GetValue := 0;
IF ok THEN
    GetValue := 42;
END_IF;
```

```st good
FUNCTION Mode : INT
VAR_INPUT
    ready : BOOL;
    busy : BOOL;
END_VAR
IMPLEMENTATION
IF NOT ready THEN
    Mode := 0;
ELSIF ready AND NOT busy THEN
    Mode := 1;
ELSIF ready AND busy THEN
    Mode := 2;
END_IF;
```

```st bad 1
FUNCTION Mode : INT
VAR_INPUT
    ready : BOOL;
    busy : BOOL;
END_VAR
IMPLEMENTATION
IF NOT ready THEN
    Mode := 0; // cts:here
ELSIF ready AND NOT busy THEN
    Mode := 1;
END_IF;
```

```st bad 1
FUNCTION AllDigits : BOOL
VAR_INPUT
    text : STRING(10);
END_VAR
VAR
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 9 DO
    IF text[i] < 48 THEN
        EXIT;
    END_IF;
    AllDigits := TRUE; // cts:here
END_FOR;
```

```st good
FUNCTION AllDigits : BOOL
VAR_INPUT
    text : STRING(10);
END_VAR
VAR
    i : INT;
END_VAR
IMPLEMENTATION
FOR i := 0 TO 9 DO
    IF text[i] < 48 OR text[i] > 57 THEN
        AllDigits := FALSE;
        EXIT;
    END_IF;
    AllDigits := TRUE;
END_FOR;
```

## When ignoring is legitimate

- Every path that reaches the caller assigns the result through a project- or
  vendor-specific mechanism not visible in the source projection.
- The function is deliberately used only for side effects and its return value
  is not part of the contract; in that case use a procedure-style POU instead.

## How to fix

Assign a safe default at the start of the function, or add assignments to all
conditional and `CASE` branches. Make the default explicit rather than relying
on controller-specific initialization behavior.

---
title: Multiple output writes
---

## What it is

Reports a `VAR_OUTPUT` itself being written more than once in the same
straight-line control-flow block. Writes to fields or elements of a structured
or array output are intentionally ignored.

## Why it is dangerous

The later assignment silently replaces the earlier value. This often means a
default or error result is being overwritten accidentally.

## Example

```st bad 1
FUNCTION F : BOOL
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
Done := FALSE;
Done := TRUE; // cts:here
F := Done;
END_FUNCTION
```

```st good
FUNCTION F : BOOL
VAR_OUTPUT
    Done : BOOL;
END_VAR
IMPLEMENTATION
IF Ready THEN
    Done := TRUE;
ELSE
    Done := FALSE;
END_IF;
F := Done;
END_FUNCTION
```

Assignments in mutually exclusive `IF`/`ELSE` or `CASE` arms are not reported.

## When ignoring is legitimate

Multiple writes can be intentional when the final assignment is a deliberate
normalization or override. Suppress the finding with a short reason in that
case.

## How to fix

Remove the redundant write, combine the conditions, or make the intended
precedence explicit.

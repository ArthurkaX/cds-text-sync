---
title: Object not reached from a task
related: [CTS0013, CTS0053]
---

## What it is

A `PROGRAM`, `FUNCTION_BLOCK`, `FUNCTION` or GVL that nothing a task runs
reaches. The reached set starts at the programs the task configuration calls
and at every object an XML file of the view names (a system event's handler,
a variable a screen shows), and grows by every object the code of a reached
object names: a call, an instance's type, a GVL or one of its variables, a
base type. A function block brings its methods, actions and properties;
`{attribute 'linkalways'}` or the object property Link Always (the
`LinkAlways` flag of the file's `(* cds-text-sync: ... *)` line) makes an
object reached on its own. An object excluded from the build
(`ExcludeFromBuild`) is left out on purpose: it is never reported, and what
its code names is not reached through it.

The rule stays silent when the view holds no task configuration, as in a
library project or a sync folder that leaves the task configuration to the
project's owner.

## Why it is dangerous

CODESYS builds only the objects it reaches from the tasks. A new POU or GVL
nobody calls compiles without an error but never gets to the PLC: a
download leaves the application's checksum as it was, and reading or writing
one of its variables fails because the symbol does not exist online.

## Example

```st good
PROGRAM MAIN
VAR
    pump : FB_Pump;
END_VAR
IMPLEMENTATION
pump(start := GVL_IO.xStart);
```

## When ignoring is legitimate

- The object is a library candidate or a template kept in the project on
  purpose and is not meant to run yet.
- Something outside the view reaches it: an object of another application,
  or an XML file the sync folder does not hold.

## How to fix

Call the program from a task, or call or declare the object from code a task
already runs (`MAIN`, a program in the task configuration). To build an object
that no code calls, give it `{attribute 'linkalways'}`. Exclude an object kept
on purpose from the build (its Properties in the IDE), or delete one that is no
longer needed.

---
title: Concurrent writes to shared data
---

## What it is

Reports qualified project data written by programs associated with different
execution contexts in the exported project model.

## Why it is dangerous

The final value can depend on execution order. This can create races or values
that are overwritten before another execution context reads them.

## Example

```st bad 1
PROGRAM FastTask
IMPLEMENTATION
// cts:gvl GVL: Shared
// cts:task FastTask: FastTask
// cts:task SlowTask: FastTask
GVL.Shared := 1; // cts:here
END_PROGRAM
```

```st good
PROGRAM FastTask
IMPLEMENTATION
GVL.Shared := 1;
END_PROGRAM
```

The bad example is reported when the same program is associated with two
different execution contexts in the project model.

## When ignoring is legitimate

- The writes are deliberately synchronized by the runtime or a handshake.
- The execution contexts are mutually exclusive in the deployed design.
- The variable is an intentionally shared command or mailbox.

## How to fix

Assign one execution context as the owner of the variable and communicate
through a clear interface, or protect the shared access with the platform's
synchronization mechanism.

---
title: Recursive POU call cycle
since: 3.1.0
related: [CTS0045, CTS0053]
---

## What it is

`CTS0085` reports a direct or indirect recursive call between project POUs.
The rule follows calls that can be resolved in the exported project view and
reports the call site that closes a recursive cycle.

## Why it is dangerous

PLC runtimes normally execute POUs with a fixed call stack. Recursion can
consume that stack until the task faults or the watchdog stops the controller.

## Example

```st bad 1
// A.st
FUNCTION A
IMPLEMENTATION
    B(); // cts:here
END_FUNCTION

// B.st
FUNCTION B
IMPLEMENTATION
    A(); // recursive cycle
END_FUNCTION
```

```st good
FUNCTION A
IMPLEMENTATION
    // Traverse with an explicit bounded loop instead of calling A again.
END_FUNCTION
```

## When ignoring is legitimate

Only ignore this finding when the exported call graph is incomplete or a call
is a deliberate platform-specific trampoline that is proven not to recurse at
runtime.

## How to fix

Replace the recursive traversal with an explicit state machine, a bounded
loop, or an iterative work list. If the call is not intended, remove the
back-edge in the POU call graph.

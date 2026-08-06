---
title: Unreachable POU
since: 3.0.0
related: [CTS0013]
---

## What it is

A callable POU cannot be reached from any program listed as a root in the
configured task projections. A POU called only by another unreachable POU is
reported with that dead call chain in the message.

The rule runs only when at least one task root is available. Without task
configuration, reachability is unknown and no finding is produced.

## Why it is dangerous

The POU may be obsolete code, a missed task assignment, or a broken call
chain. Keeping it in the project makes maintenance harder and can hide logic
that the author believed was running.

## Example

```st bad 2
PROGRAM Main
IMPLEMENTATION
MainWork();
END_PROGRAM

FUNCTION Orphan
IMPLEMENTATION
Leaf();
END_FUNCTION

FUNCTION Leaf // cts:here
IMPLEMENTATION
END_FUNCTION
```

```st good
PROGRAM Main
IMPLEMENTATION
Orphan();
END_PROGRAM

FUNCTION Orphan
IMPLEMENTATION
Leaf();
END_FUNCTION

FUNCTION Leaf
IMPLEMENTATION
END_FUNCTION
```

In the bad example, `Orphan` and `Leaf` are not reachable from the task root
`Main`; `Leaf` is reachable only through the unreachable `Orphan`.

## When ignoring is legitimate

- The POU is an entry point invoked by a mechanism not represented in the
  exported task configuration.
- The POU is retained for commissioning, diagnostics, or a future feature.
- The project snapshot does not contain the complete task configuration.

## How to fix

Add the intended program to a task, connect the POU to a reachable call chain,
or remove the unused code. If the entry point is external, keep the task or
integration configuration in the analyzed project view.

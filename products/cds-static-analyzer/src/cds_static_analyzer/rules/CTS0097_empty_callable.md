---
title: Empty callable implementation
since: 3.1.0
related: [CTS0023, CTS0045]
---

## What it is

`CTS0097` reports a `PROGRAM`, `FUNCTION_BLOCK`, `FUNCTION`, method, action,
or property with an empty implementation section.

## Why it is dangerous

An empty callable often remains after a skeleton was created for a feature that
was never implemented. It is easy to overlook because the project still
compiles, while callers may silently execute no logic.

Comment-only and semicolon-only implementations are treated as empty. The
rule does not replace `CTS0045`, which checks reachability.

## Example

```st bad 1
FUNCTION_BLOCK FB_Reserved // cts:here
IMPLEMENTATION
// TODO: implement the state machine
```

```st good
FUNCTION_BLOCK FB_Reserved
IMPLEMENTATION
xReady := TRUE; // cts:here is intentionally not empty
```

## When ignoring is legitimate

Ignore deliberate lifecycle hooks, generated extension points, and compatibility
stubs when their empty behavior is part of the documented contract.

## How to fix

Implement the callable, remove it, or add a concise comment explaining the
intentional stub and suppress the finding with a reason.

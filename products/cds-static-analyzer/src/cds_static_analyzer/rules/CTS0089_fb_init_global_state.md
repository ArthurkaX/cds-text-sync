---
title: Global state access during FB_Init
since: 3.1.0
related: [CTS0025]
---

## What it is

`FB_Init` writes global state or uses a global function-block instance while
the project is still initializing:

```st
METHOD FB_Init : BOOL
    gReady := TRUE;
    gController.Start();
END_METHOD
```

## Why it is dangerous

Initialization order between separate FB instances and global state is easy to
misread. A startup-only failure may occur when one FB observes another FB or a
global flag before its initialization has completed.

The rule intentionally does not report ordinary reads of scalar configuration
values. It reports writes and accesses that can mutate or consume stateful
global FBs.

## Example

```st bad 2
METHOD FB_Init : BOOL
// cts:owner Controller
// cts:fb Controller
// cts:gvl Globals: gController Controller
// cts:gvl Globals: gReady BOOL
    gReady := TRUE; // startup ordering dependency // cts:here
gController.Start(); // cts:here
END_METHOD
```

```st good
METHOD FB_Init : BOOL
// cts:owner Controller
// cts:fb Controller
// cts:gvl Globals: gController Controller
// cts:gvl Globals: gReady BOOL
    xReady := TRUE;
END_METHOD
```

## When ignoring is legitimate

Ignore when a project-level startup contract explicitly initializes the global
state before this FB and that order is guaranteed by the runtime configuration.

## How to fix

Pass configuration through the FB's initialization inputs, or perform the
cross-object coordination from a deliberate startup program after all FB
instances have been initialized.

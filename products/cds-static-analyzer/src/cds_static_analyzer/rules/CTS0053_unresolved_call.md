---
title: Unresolved call
since: 3.1.0
related: [CTS0045]
---

## What it is

A call cannot be resolved to a POU in the project or to a known IEC/CODESYS
library symbol. Standard functions, standard function blocks, and explicit
type-conversion functions are excluded from this check.

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

## When ignoring is legitimate

- The call belongs to a vendor library or runtime extension that is not part
  of the analyzed project view.
- The call is generated or bound by the target runtime.
- A dynamic dispatch mechanism resolves the symbol outside static analysis.

## How to fix

Correct the spelling, export the missing library declaration, or configure the
project view so the external dependency is available. Suppress the finding
when the external call is intentional and documented.

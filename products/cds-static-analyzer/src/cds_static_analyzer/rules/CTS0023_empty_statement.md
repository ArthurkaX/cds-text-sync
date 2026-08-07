---
title: Empty statement
since: 3.0.0
related: [CTS0007, CTS0016]
---

## What it is

An implementation contains a standalone semicolon or an extra semicolon after
another statement. Terminators belonging to valid statements and block
constructs are not reported.

## Why it is dangerous

Empty statements make control flow harder to scan and often remain after code
was deleted or edited manually. They can also conceal a missing statement.

## Example

```st bad 1
PROGRAM P
IMPLEMENTATION
; // cts:here
DoWork();
```

```st good
PROGRAM P
IMPLEMENTATION
DoWork();
IF Ready THEN
    DoWork();
END_IF;
```

## When ignoring is legitimate

- Generated source uses a deliberate empty statement as a formatting marker.
- A vendor-specific preprocessor requires the extra terminator.
- A directly preceding comment explicitly documents an intentional wait, reset,
  reserved hook, or other no-op branch.

## How to fix

Remove the standalone or duplicate semicolon.

---
title: Assigned local not read
since: 3.0.0
related: [CTS0002, CTS0009]
---

## What it is

A local `VAR`, `VAR_TEMP`, or `VAR_STAT` variable receives a value, but the
value is never read afterward (or anywhere else in the callable).

## Why it is dangerous

This often means that a calculation was started and then forgotten, or that a
previously used variable became obsolete. The assignment may be dead code and
can hide a missing output assignment or an incomplete control path.

## Example

```st bad 1
PROGRAM P
VAR
    calculated : INT;  // cts:here
END_VAR
IMPLEMENTATION
calculated := limit + offset;
END_PROGRAM
```

```st good
PROGRAM P
VAR
    calculated : INT;
END_VAR
IMPLEMENTATION
calculated := limit + offset;
result := calculated;
END_PROGRAM
```

## Limitations

The rule checks direct local assignments and reads in the same callable. It
does not attempt interprocedural or pointer/alias analysis.

## When ignoring is legitimate

- The assignment is required by a vendor convention or external interface.
- The value is consumed through an alias or runtime mechanism not visible to
  the analyzer.
- The code is an intentional placeholder during development.

## How to fix

Remove the unused calculation, use the variable where intended, or suppress
the finding when the assignment is required for an external side effect.

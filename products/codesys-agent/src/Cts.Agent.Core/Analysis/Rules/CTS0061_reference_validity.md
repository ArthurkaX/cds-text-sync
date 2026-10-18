---
title: Unchecked reference use
since: 3.1.0
related: [CTS0051]
---

## What it is

A `REFERENCE` is accessed without a dominating `__ISVALIDREF` check.

## Why it is dangerous

An unassigned or invalid reference can make an otherwise ordinary member
access target undefined storage.

## Example

```st bad 1
PROGRAM Main
VAR
    refData : REFERENCE TO Data;
END_VAR
IMPLEMENTATION
value := refData.value; // cts:here
END_PROGRAM
```

```st good
IF __ISVALIDREF(refData) THEN
    value := refData.value;
END_IF;
```

## When ignoring is legitimate

- The reference is assigned by a lifecycle contract before this POU is
  entered, and the contract is enforced outside the analyzed source.
- The vendor runtime guarantees initialization for this reference.

## How to fix

Validate the reference with `__ISVALIDREF` before member or element access,
or leave the invalid branch immediately.

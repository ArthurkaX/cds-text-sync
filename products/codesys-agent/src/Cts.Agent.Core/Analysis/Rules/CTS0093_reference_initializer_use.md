---
title: Reference use in declaration initializer
since: 3.1.0
related: [CTS0061, CTS0092]
---

## What it is

`CTS0093` reports reading a `REFERENCE` in a declaration initializer, for
example while reading one of its fields.

## Why it is dangerous

The initializer runs before the POU body. A later `__ISVALIDREF` check cannot
protect a reference that was already read during declaration setup.

## Example

```st bad 1
PROGRAM Main
VAR
    refData : REFERENCE TO Data;
    value : INT := refData.nValue; // validity is unchecked // cts:here
END_VAR
IMPLEMENTATION
```

```st good
PROGRAM Main
VAR
    refData : REFERENCE TO Data;
    value : INT;
END_VAR
IMPLEMENTATION
IF __ISVALIDREF(refData) THEN
    value := refData.nValue;
END_IF;
```

## When ignoring is legitimate

Binding a reference itself is intentionally allowed:

```st
refData : REFERENCE TO Data := sourceData;
```

Ignore a value read only when an external startup contract guarantees the
reference before declaration initialization.

## How to fix

Move the read into the implementation after `__ISVALIDREF`, or initialize the
destination from a safe scalar or structure default.

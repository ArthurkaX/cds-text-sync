---
title: Pointer dereference in declaration initializer
since: 3.1.0
related: [CTS0060]
---

## What it is

`CTS0092` reports a pointer dereference inside a variable declaration
initializer.

## Why it is dangerous

Declaration initializers run before the POU body. A later null check cannot
protect an expression that already dereferenced the pointer during setup.

## Example

```st bad 1
PROGRAM Main
VAR
    pValue : POINTER TO INT;
    value : INT := pValue^; // no body guard can protect this // cts:here
END_VAR
IMPLEMENTATION
IF pValue <> 0 THEN
    value := pValue^;
END_IF;
```

```st good
PROGRAM Main
VAR
    pValue : POINTER TO INT;
    value : INT;
END_VAR
IMPLEMENTATION
IF pValue <> 0 THEN
    value := pValue^;
END_IF;
```

## When ignoring is legitimate

Ignore only when the pointer is guaranteed by an external initialization
contract before the declaration initializer executes. Make that contract
visible in the POU where possible.

## How to fix

Move the dereference into the implementation after a dominating non-null
check, or initialize the value from a safe scalar default.

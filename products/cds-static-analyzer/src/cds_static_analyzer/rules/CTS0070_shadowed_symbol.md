---
title: Shadowed symbol
since: 3.1.0
related: [CTS0033]
---

## What it is

A local or interface symbol has the same name as a global variable or a
member of the owning function block.

## Why it is dangerous

An unqualified reference can silently resolve to the nearer declaration.
Renaming or adding a member can therefore change behavior without changing
the apparent business logic.

## Example

```st bad 1
VAR_GLOBAL
    xReady : BOOL;
END_VAR

PROGRAM Main
VAR
    xReady : BOOL; // cts:here
END_VAR
IMPLEMENTATION
```

```st good
VAR_GLOBAL
    xReady : BOOL;
END_VAR

PROGRAM Main
VAR
    xLocalReady : BOOL;
END_VAR
IMPLEMENTATION
```

## When ignoring is legitimate

- A generated wrapper intentionally mirrors an external symbol name.
- The declaration is isolated from the code that uses the other symbol.

## How to fix

Rename the local symbol or qualify the intended owner explicitly.

---
title: Bit index outside type width
since: 3.1.0
related: []
---

## What it is

A bit access uses a literal index outside the width of a known integer or bit
string type.

## Why it is dangerous

The access can be rejected by the compiler or behave differently across
targets, and usually indicates an off-by-one error.

## Example

```st bad 1
VAR
    b : BYTE;
END_VAR
b.8 := TRUE; // cts:here
```

```st good
b.7 := TRUE;
```

## When ignoring is legitimate

- The code is generated for a target with a documented extension.
- The declaration is replaced by a wider type before deployment.

## How to fix

Use an index from `0` through `width - 1`, or use a type with sufficient width.
